import pytest
from botocore.stub import Stubber
import boto3
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

def test_s3_object_exists(s3_storage, stubber):
    expected_params = {'Bucket': 'test-bucket', 'Key': 'test-key'}
    stubber.add_response('head_object', {}, expected_params)
    assert s3_storage.object_exists('test-key') is True
    
    stubber.add_client_error('head_object', '404', 'Not Found')
    assert s3_storage.object_exists('missing-key') is False

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
