import pytest
from botocore.stub import Stubber
import boto3
from botocore.exceptions import ClientError
from backend.services.evidence_storage import S3Storage, EvidenceNotFoundError, StorageUploadError

@pytest.fixture
def s3_storage():
    return S3Storage(
        endpoint=None,
        bucket="test-bucket",
        access_key="test",
        secret_key="test",
        region="us-east-1"
    )

@pytest.fixture
def stubber(s3_storage):
    s3_client = s3_storage.s3
    with Stubber(s3_client) as stubber:
        yield stubber

def test_s3_put_object(s3_storage, stubber):
    expected_params = {
        'Bucket': 'test-bucket',
        'Key': 'test-key',
        'Body': b'test-data',
        'ContentType': 'image/jpeg'
    }
    stubber.add_response('put_object', {}, expected_params)
    
    s3_storage.put_object('test-key', b'test-data', 'image/jpeg')
    stubber.assert_no_pending_responses()

def test_s3_put_object_failure(s3_storage, stubber):
    stubber.add_client_error('put_object', 'AccessDenied', 'Access Denied')
    with pytest.raises(StorageUploadError, match="Failed to upload to S3:"):
        s3_storage.put_object('test-key', b'test-data', 'image/jpeg')

def test_s3_get_object(s3_storage, stubber):
    import io
    from botocore.response import StreamingBody
    
    body = StreamingBody(io.BytesIO(b'test-data'), len(b'test-data'))
    
    expected_params = {'Bucket': 'test-bucket', 'Key': 'test-key'}
    stubber.add_response('get_object', {'Body': body}, expected_params)
    
    data = s3_storage.get_object('test-key')
    assert data == b'test-data'
    stubber.assert_no_pending_responses()

def test_s3_get_object_missing(s3_storage, stubber):
    stubber.add_client_error('get_object', 'NoSuchKey', 'The specified key does not exist.')
    with pytest.raises(EvidenceNotFoundError):
        s3_storage.get_object('test-key')


def test_s3_get_object_http_404_with_blank_code_is_missing(s3_storage, stubber):
    stubber.add_client_error('get_object', '', '', http_status_code=404)
    with pytest.raises(EvidenceNotFoundError):
        s3_storage.get_object('empty-key')


@pytest.mark.parametrize('status, code', [(403, 'AccessDenied'), (500, 'InternalError')])
def test_s3_get_object_non_missing_errors_are_not_swallowed(s3_storage, stubber, status, code):
    stubber.add_client_error('get_object', code, 'safe failure', http_status_code=status)
    with pytest.raises(ClientError):
        s3_storage.get_object('test-key')

def test_s3_head_object(s3_storage, stubber):
    expected_params = {'Bucket': 'test-bucket', 'Key': 'test-key'}
    stubber.add_response('head_object', {'ContentLength': 100}, expected_params)
    
    meta = s3_storage.head_object('test-key')
    assert meta['ContentLength'] == 100
    stubber.assert_no_pending_responses()

def test_s3_head_object_missing(s3_storage, stubber):
    stubber.add_client_error('head_object', '404', 'Not Found')
    with pytest.raises(EvidenceNotFoundError):
        s3_storage.head_object('test-key')


def test_s3_head_object_http_404_with_unusual_code_is_missing(s3_storage, stubber):
    stubber.add_client_error('head_object', 'NoSuchObject', 'not found', http_status_code=404)
    with pytest.raises(EvidenceNotFoundError):
        s3_storage.head_object('missing-key')

def test_s3_object_exists(s3_storage, stubber):
    expected_params = {'Bucket': 'test-bucket', 'Key': 'test-key'}
    stubber.add_response('head_object', {}, expected_params)
    assert s3_storage.object_exists('test-key') is True
    
    stubber.add_client_error('head_object', '404', 'Not Found')
    assert s3_storage.object_exists('missing-key') is False


def test_s3_object_exists_non_missing_error_is_not_swallowed(s3_storage, stubber):
    stubber.add_client_error('head_object', 'InternalError', 'safe failure', http_status_code=500)
    with pytest.raises(ClientError):
        s3_storage.object_exists('test-key')


def test_s3_diagnostics_do_not_log_secrets(s3_storage, stubber, caplog):
    caplog.set_level('WARNING')
    stubber.add_client_error(
        'get_object',
        'AccessDenied',
        'Authorization=secret-token https://example.invalid/signed?X-Amz-Signature=secret',
        http_status_code=403,
    )
    with pytest.raises(ClientError):
        s3_storage.get_object('test-key')
    text = caplog.text
    assert 'AccessDenied' in text and '403' in text
    assert 'secret-token' not in text
    assert 'X-Amz-Signature' not in text
    assert 'example.invalid' not in text

def test_s3_delete_object(s3_storage, stubber):
    expected_params = {'Bucket': 'test-bucket', 'Key': 'test-key'}
    stubber.add_response('delete_object', {}, expected_params)
    
    s3_storage.delete_object('test-key')
    stubber.assert_no_pending_responses()

def test_s3_generate_signed_url(s3_storage):
    # generate_presigned_url doesn't make API calls directly, so stubber isn't strictly required
    url = s3_storage.generate_signed_url('test-key')
    assert url is not None
    assert 'test-bucket' in url
    assert 'test-key' in url
    assert 'Signature=' in url or 'X-Amz-Signature=' in url


def test_s3_custom_endpoint_uses_path_style_addressing():
    storage = S3Storage(
        endpoint="https://project-ref.storage.supabase.co/storage/v1/s3",
        bucket="test-bucket",
        access_key="test",
        secret_key="test",
        region="ap-south-1",
    )

    assert storage.s3.meta.config.s3["addressing_style"] == "path"
