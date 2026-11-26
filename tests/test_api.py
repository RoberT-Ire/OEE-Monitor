import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.config import Settings, hash_password

@pytest.fixture(scope='module')
def app(tmp_path_factory):
    settings = Settings(True, 'sqlite:///' + str(tmp_path_factory.mktemp('db') / 'test.db'), 'test-secret-' * 4, False, 120, {
        'engineer': {'password_hash': hash_password('demo-engineer'), 'role':'engineer','machines':['*']},
        'operator': {'password_hash': hash_password('demo-operator'), 'role':'operator','machines':['BOT-01']},
    })
    return create_app(settings)

@pytest.fixture(scope='module')
def client(app):
    with TestClient(app) as c:
        yield c

@pytest.fixture(autouse=True)
def clear_cookie(client):
    client.cookies.clear()


def login(client, name='engineer', password='demo-engineer'):
    return client.post('/api/login', json={'username':name,'password':password}, headers={'X-Monitor-Request':'1'})


def test_public_page(client):
    assert client.get('/').status_code == 200
    assert client.get('/api/config').json()['demo'] is True


def test_protected(client):
    assert client.get('/api/machines').status_code == 401
    assert client.get('/api/machines/BOT-01/dashboard').status_code == 401


def test_login_invalid(client):
    assert login(client, password='invalid').status_code == 401
    assert client.post('/api/login',json={'username':'engineer','password':'demo-engineer'}).status_code == 403


def test_engineer_dashboard(client):
    assert login(client).status_code == 200
    assert len(client.get('/api/machines').json()) == 12
    r=client.get('/api/machines/BOT-01/dashboard?hours=24')
    assert r.status_code == 200
    d=r.json()
    assert d['latest']['units_per_min'] is not None
    assert 0 <= d['metrics']['coverage_pct'] <= 100
    assert 0 <= d['metrics']['running_pct'] <= 100
    assert len(d['series']) <= 600
    assert d['series'][0]['time'] <= d['series'][-1]['time']
    assert d['series'][0]['segments']
    assert d['events']
    assert client.get('/api/machines/BOT-01/dashboard?hours=25').status_code == 422
    assert client.get('/api/machines/nonexistent/dashboard').status_code == 404


def test_operator_scope(client):
    assert login(client,'operator','demo-operator').status_code == 200
    assert [m['id'] for m in client.get('/api/machines').json()] == ['BOT-01']
    assert client.get('/api/machines/BOT-01/dashboard').status_code == 200
    assert client.get('/api/machines/LAB-02/dashboard').status_code == 403


def test_logout(client):
    assert login(client).status_code == 200
    assert client.post('/api/logout').status_code == 403
    assert client.post('/api/logout',headers={'X-Monitor-Request':'1'}).status_code == 200
    assert client.get('/api/me').status_code == 401


def test_overview(client):
    assert login(client).status_code == 200
    r=client.get('/api/overview?days=7').json()
    assert len(r['buildings'])==5 and len(r['machines'])==12 and len(r['trend'])==7
    assert 0 < r['metrics']['oee'] < 100
    assert abs(r['metrics']['oee']-r['metrics']['availability']*r['metrics']['performance']*r['metrics']['quality']/10000)<.2
    assert any(m['status']=='offline' for m in r['machines'])
    assert len(client.get('/api/overview?building=liquid').json()['machines'])==3
    assert client.get('/api/reports').status_code==200
    assert client.get('/api/machines/BOT-01/metrics').status_code==200


def test_operator_permissions_v2(client):
    assert login(client,'operator','demo-operator').status_code==200
    d=client.get('/api/overview').json()
    assert len(d['machines'])==1 and len(d['available_buildings'])==1
    assert client.get('/api/overview?building=blister').status_code==404
    assert client.get('/api/reports').status_code==403
    assert client.get('/api/machines/BL-01/metrics').status_code==403
    d=client.get('/api/machines/BOT-01/dashboard').json()
    assert 'temperature_c' not in d['latest'] and 'temperature_c' not in d['series'][0]
