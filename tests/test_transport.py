import httpx,pytest
from loopgrid_langchain import CoreClient, LoopGridError, validate_origin

@pytest.mark.parametrize('ok',[
    'https://core.example.invalid','https://core.example.invalid/','http://localhost:8000',
    'http://127.0.0.1:8000','http://[::1]:8000',
])
def test_safe_origin(ok): assert validate_origin(ok).startswith(('http://','https://'))

@pytest.mark.parametrize('bad',[
    '', 'garbage', 'file:///etc/passwd','http://core.example.invalid',
    'https://name:password@core.example.invalid', 'https://core.example.invalid/path',
    'https://core.example.invalid?token=x','https://core.example.invalid/#fragment',
    'https://core.example.invalid/%2fsecret','https://core.example.invalid\\attack',
])
def test_invalid_origin(bad):
    with pytest.raises(ValueError):validate_origin(bad)

def test_header_and_no_redirect():
    seen=[]
    def handler(request):
        seen.append(request)
        return httpx.Response(200,json={'decision_id':'dec_123456'})
    client=CoreClient(base_url='https://core.example.invalid',workspace_id='ws_test',
                      service_key='private-test-key',transport=httpx.MockTransport(handler))
    client.create_decision({'decision_type':'test'})
    assert seen[0].headers['X-LoopGrid-Key']=='private-test-key'
    assert seen[0].url.path=='/api/v1/decisions'
    assert b'ws_test' in seen[0].content

def test_redirect_refused_with_key_not_forwarded():
    visits=[]
    def handler(request):
        visits.append(request)
        return httpx.Response(302,headers={'Location':'https://attacker.invalid/secret'})
    client=CoreClient(base_url='https://core.example.invalid',workspace_id='ws_test',
                      service_key='secret-token',transport=httpx.MockTransport(handler))
    with pytest.raises(LoopGridError,match='HTTP 302'):client.verify_workspace()
    assert len(visits)==1

def test_raw_server_secrets_not_in_errors():
    def handler(request):return httpx.Response(500,json={'error':'secret-token'} )
    client=CoreClient(base_url='https://core.example.invalid',workspace_id='ws_test',
                      service_key='secret-token',transport=httpx.MockTransport(handler))
    with pytest.raises(LoopGridError) as e:client.verify_workspace()
    assert 'secret-token' not in str(e.value)

def test_json_and_type_bounds():
    for response in [httpx.Response(200,content=b'invalid'),httpx.Response(200,json=['not a dict'])]:
        client=CoreClient(base_url='https://core.example.invalid',workspace_id='ws_test',
                          transport=httpx.MockTransport(lambda request:response))
        with pytest.raises(LoopGridError):client.verify_workspace()

def test_response_size_bounded():
    client=CoreClient(base_url='https://core.example.invalid',workspace_id='ws_test',
         transport=httpx.MockTransport(lambda request:httpx.Response(200,content=b'a'*2_100_000)))
    with pytest.raises(LoopGridError,match='too large'):client.verify_workspace()

def test_network_failure_sanitized():
    def handler(request):raise httpx.ConnectError('secret-token',request=request)
    client=CoreClient(base_url='https://core.example.invalid',workspace_id='ws_test',
                      transport=httpx.MockTransport(handler))
    with pytest.raises(LoopGridError) as e:client.verify_workspace()
    assert 'secret-token' not in str(e.value)

def test_workspace_id_required():
    with pytest.raises(ValueError):CoreClient(base_url='https://core.example.invalid',workspace_id='bad/id')
