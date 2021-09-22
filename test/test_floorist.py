import logging
import pytest
import sys
import yaml

from botocore.exceptions import NoCredentialsError
from os import environ as env
from psycopg2 import OperationalError
from s3fs import S3FileSystem
from yaml.parser import ParserError

sys.path.append('./app-src')
import app

class TestFloorist:
  @pytest.fixture(autouse=True)
  def setup_env(self):
    with open('test/env.yaml', 'r') as stream:
      settings = yaml.safe_load(stream)
      for key in settings:
        env[key] = settings[key]

  @pytest.mark.parametrize('key', ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_REGION'])
  def test_unset_s3_credentials(self, key):
    # FIXME: botocore caches the environment variables in a weird way, so their deletion
    # leaks into other tests and affects them, even if the variables are reset after each run
    return

    del env[key]
    with pytest.raises(NoCredentialsError):
      app.main()

  def test_invalid_s3_credentials(self):
    del env['AWS_ENDPOINT']
    with pytest.raises(PermissionError) as ex:
      app.main()
    assert 'AWS' in str(ex.value)

  def test_unset_s3_bucket(self):
    del env['AWS_BUCKET']
    with pytest.raises(KeyError) as ex:
      app.main()
    assert 'AWS_BUCKET' in str(ex.value)

  def test_missing_s3_bucket(self):
    env['AWS_BUCKET'] = 'foo'
    with pytest.raises(FileNotFoundError) as ex:
      app.main()
    assert 'bucket does not exist' in str(ex.value)

  @pytest.mark.parametrize('key', ['POSTGRES_SERVICE_HOST', 'POSTGRESQL_USER', 'POSTGRESQL_DATABASE', 'POSTGRESQL_PASSWORD'])
  def test_missing_pg_credentials(self, key):
    del env[key]
    with pytest.raises(KeyError) as ex:
      app.main()
    assert key in str(ex.value)

  def test_invalid_pg_credentials(self):
    env['POSTGRESQL_USER'] = 'foo'
    with pytest.raises(OperationalError) as ex:
      app.main()

  def test_invalid_pg_databae(self):
    env['POSTGRESQL_DATABASE'] = 'foo'
    with pytest.raises(OperationalError) as ex:
      app.main()
    assert 'database "foo" does not exist' in str(ex.value)

  def test_unset_floorplan(self):
    with pytest.raises(KeyError) as ex:
      app.main()
    assert 'FLOORPLAN_FILE' in str(ex.value)

  def test_missing_floorplan(self):
    env['FLOORPLAN_FILE'] = 'foo'
    with pytest.raises(FileNotFoundError):
      app.main()

  def test_invalid_floorplan(self):
    env['FLOORPLAN_FILE'] = 'Dockerfile'
    with pytest.raises(ParserError):
      app.main()

  def test_floorplan_without_query(self, caplog):
    env['FLOORPLAN_FILE'] = 'test/floorplan_without_query.yaml'
    with pytest.raises(SystemExit) as ex:
      app.main()
    assert ex.value.code == 1
    assert 'query' in caplog.text
    assert 'KeyError' in caplog.text

  def test_floorplan_without_prefix(self, caplog):
    env['FLOORPLAN_FILE'] = 'test/floorplan_without_prefix.yaml'
    with pytest.raises(SystemExit) as ex:
      app.main()
    assert ex.value.code == 1
    assert 'KeyError' in caplog.text
    assert 'prefix' in caplog.text

  def test_floorplan_with_invalid_query(self, caplog):
    env['FLOORPLAN_FILE'] = 'test/floorplan_with_invalid_query.yaml'
    with pytest.raises(SystemExit) as ex:
      app.main()
    assert ex.value.code == 1
    assert 'DatabaseError' in caplog.text

  def test_floorplan_with_invalid_prefix(self, caplog):
    env['FLOORPLAN_FILE'] = 'test/floorplan_with_invalid_prefix.yaml'
    with pytest.raises(SystemExit) as ex:
      app.main()
    assert ex.value.code == 1
    assert 'XMinioInvalidObjectName' in caplog.text

  def test_floorplan_with_multiple_dumps(self, caplog):
    s3 = S3FileSystem(client_kwargs={'endpoint_url': env.get('AWS_ENDPOINT') })
    if s3.ls(env['AWS_BUCKET']) != []: # Make sure that the bucket is empty
      s3.rm(f"{env['AWS_BUCKET']}/*", recursive=True)

    assert s3.ls(env['AWS_BUCKET']) == []
    env['FLOORPLAN_FILE'] = 'test/floorplan_with_multiple_dumps.yaml'
    app.main()
    assert 'Dumped 2 from total of 2'
    assert s3.ls(env['AWS_BUCKET']) == [f"{env['AWS_BUCKET']}/numbers", f"{env['AWS_BUCKET']}/people"]

  def test_floorplan_with_one_failing_dump(self, caplog):
    s3 = S3FileSystem(client_kwargs={'endpoint_url': env.get('AWS_ENDPOINT') })
    if s3.ls(env['AWS_BUCKET']) != []: # Make sure that the bucket is empty
      s3.rm(f"{env['AWS_BUCKET']}/*", recursive=True)

    env['FLOORPLAN_FILE'] = 'test/floorplan_with_one_failing_dump.yaml'
    with pytest.raises(SystemExit) as ex:
      app.main()
    assert ex.value.code == 1
    assert 'DatabaseError' in caplog.text
    assert 'Dumped 1 from total of 2'
    assert s3.ls('floorist') == [f"{env['AWS_BUCKET']}/numbers"]
