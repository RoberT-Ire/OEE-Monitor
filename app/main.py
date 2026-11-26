import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import timedelta, timezone
from pathlib import Path
import time
from collections import defaultdict, deque
from threading import Lock
from fastapi import FastAPI, HTTPException, Request, Depends, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, desc, func
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.sessions import SessionMiddleware
from .config import Settings, verify_password, hash_password
from .database import make_database, Building, Machine, Reading, DailyMetric, Loss
from .demo import seed, tick, utcnow

STATIC = Path(__file__).parent / 'static'
MAX_ROWS = 20_000
VALID_STATUS = {'running', 'stopped', 'warning', 'not_scheduled'}


def iso(t):
    return t.replace(tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z')


def reading_dict(r):
    return {'time': iso(r.recorded_at), 'status': r.status if r.status in VALID_STATUS else 'unknown',
            'temperature_c': r.temperature_c, 'vibration_mm_s': r.vibration_mm_s,
            'motor_rpm': r.motor_rpm, 'units_per_min': r.units_per_min}


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=300)


def create_app(settings=None):
    settings = settings or Settings.from_env()
    engine, sessions = make_database(settings.database_url)
    dummy_hash = hash_password('unused')
    attempts = defaultdict(deque)
    attempt_lock = Lock()

    async def simulate():
        while True:
            await asyncio.sleep(10)
            await asyncio.to_thread(tick, sessions)

    @asynccontextmanager
    async def lifespan(app):
        task = None
        if settings.demo:
            await asyncio.to_thread(seed, engine, sessions)
            task = asyncio.create_task(simulate())
        try:
            yield
        finally:
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            engine.dispose()

    app = FastAPI(title='Machine Monitor API', version='2.0.0', lifespan=lifespan,
                  docs_url='/docs' if settings.demo else None, redoc_url=None,
                  openapi_url='/openapi.json' if settings.demo else None)
    app.add_middleware(SessionMiddleware, secret_key=settings.secret, https_only=settings.secure_cookie,
                       same_site='strict', max_age=8 * 3600, session_cookie='monitor_session')
    app.mount('/static', StaticFiles(directory=STATIC), name='static')

    @app.middleware('http')
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        if not request.url.path.startswith('/docs'):
            response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if request.url.path.startswith('/api/') or request.url.path == '/':
            response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(SQLAlchemyError)
    async def db_error(request, exc):
        return JSONResponse(status_code=503, content={'detail': 'Sensor database is temporarily unavailable.'})

    def current_user(request: Request):
        name = request.session.get('username')
        account = settings.users.get(name)
        if not account:
            raise HTTPException(401, 'Please sign in.')
        return {'username': name, 'role': account['role'], 'machines': account['machines']}

    def permitted(user, mid):
        return '*' in user['machines'] or mid in user['machines']

    @app.get('/', include_in_schema=False)
    def index():
        return FileResponse(STATIC / 'index.html')

    @app.get('/api/config')
    def config():
        return {'demo': settings.demo, 'sample_data': settings.demo or settings.sample_data, 'refresh_seconds': 10}

    @app.post('/api/login')
    def login(body: Login, request: Request):
        # Custom header plus JSON prevents ordinary cross-site form submissions.
        if request.headers.get('X-Monitor-Request') != '1':
            raise HTTPException(403, 'Invalid request.')
        key = request.client.host if request.client else 'unknown'
        now = time.monotonic()
        with attempt_lock:
            for k in list(attempts):
                if not attempts[k] or now - attempts[k][-1] > 60:
                    attempts.pop(k, None)
            q = attempts[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= 10:
                raise HTTPException(429, 'Too many attempts. Try again in a minute.')
            q.append(now)
        account = settings.users.get(body.username)
        valid = verify_password(body.password, account['password_hash'] if account else dummy_hash)
        if not account or not valid:
            raise HTTPException(401, 'Incorrect username or password.')
        request.session.clear()
        request.session['username'] = body.username
        return {'username': body.username, 'role': account['role']}

    @app.post('/api/logout')
    def logout(request: Request):
        if request.headers.get('X-Monitor-Request') != '1':
            raise HTTPException(403, 'Invalid request.')
        request.session.clear()
        return {'ok': True}

    @app.get('/api/me')
    def me(user=Depends(current_user)):
        return {'username': user['username'], 'role': user['role']}

    @app.get('/api/machines')
    def machines(user=Depends(current_user)):
        with sessions() as db:
            query = select(Machine).order_by(Machine.id)
            if '*' not in user['machines']:
                query = query.where(Machine.id.in_(user['machines']))
            return [{'id': m.id, 'name': m.name, 'line': m.line, 'building_id': m.building_id} for m in db.scalars(query)]

    @app.get('/api/machines/{machine_id}/dashboard')
    def dashboard(machine_id: str, hours: int = Query(6, ge=1, le=24), user=Depends(current_user)):
        if not permitted(user, machine_id):
            raise HTTPException(403, 'You do not have access to this machine.')
        now = utcnow()
        start = now - timedelta(hours=hours)
        with sessions() as db:
            machine = db.get(Machine, machine_id)
            if not machine:
                raise HTTPException(404, 'Machine not found.')
            base = select(Reading).where(Reading.machine_id == machine_id, Reading.recorded_at <= now)
            order = (desc(Reading.recorded_at), desc(Reading.id))
            latest = db.scalar(base.order_by(*order).limit(1))
            rows = list(db.scalars(base.where(Reading.recorded_at >= start).order_by(*order).limit(MAX_ROWS + 1)))
            truncated = len(rows) > MAX_ROWS
            rows = list(reversed(rows[:MAX_ROWS]))
            stale = latest is None or (now - latest.recorded_at).total_seconds() > settings.stale_seconds
            # Estimate time only for intervals bounded by consecutive readings, with a gap limit.
            observed = running = stopped = 0.0
            events = []
            for a, b in zip(rows, rows[1:]):
                dt = (b.recorded_at - a.recorded_at).total_seconds()
                if dt <= 0 or dt > settings.stale_seconds:
                    continue
                if a.status in ('running', 'warning', 'stopped'):
                    observed += dt
                    running += dt if a.status in ('running', 'warning') else 0
                    stopped += dt if a.status == 'stopped' else 0
                if a.status != b.status and b.status in VALID_STATUS:
                    events.append({'time': iso(b.recorded_at), 'status': b.status})
            # Keep chart payload bounded, retain first/last, and do not calculate KPIs from sampled points.
            stride = max(1, (len(rows) + 598) // 599)
            fields = ('temperature_c', 'vibration_mm_s', 'motor_rpm', 'units_per_min')
            segments = dict.fromkeys(fields, 0)
            chart_rows = []
            previous = None
            for i, r in enumerate(rows):
                if previous is not None:
                    gap = (r.recorded_at - previous.recorded_at).total_seconds() > settings.stale_seconds
                    for field in fields:
                        if gap or getattr(previous, field) is None or getattr(r, field) is None:
                            segments[field] += 1
                if i % stride == 0 or i == len(rows) - 1:
                    chart_rows.append({**reading_dict(r), 'segments': segments.copy()})
                previous = r
            return {'machine': {'id': machine.id, 'name': machine.name, 'line': machine.line},
                    'status': 'offline' if stale else reading_dict(latest)['status'],
                    'latest': (reading_dict(latest) if user['role'] != 'operator' else {'time': iso(latest.recorded_at), 'status': latest.status, 'units_per_min': latest.units_per_min}) if latest else None,
                    'stale': stale, 'hours': hours, 'generated_at': iso(now), 'window_start': iso(start),
                    'metrics': {'running_pct': round(100 * running / observed, 1) if observed else None,
                                'downtime_minutes': round(stopped / 60, 1) if observed else None,
                                'coverage_pct': round(100 * observed / (hours * 3600), 1),
                                'samples': len(rows)},
                    'series': chart_rows if user['role'] != 'operator' else [{k:v for k,v in r.items() if k in ('time','status','units_per_min','segments')} for r in chart_rows], 'events': list(reversed(events[-12:])),
                    'truncated': truncated, 'chart_sampled': stride > 1, 'gap_seconds': settings.stale_seconds}

    def kpis(rows):
        # Time-weighted OEE. Invalid records are excluded, not silently clamped.
        valid = [r for r in rows if r.planned_minutes > 0 and 0 <= r.run_minutes <= r.planned_minutes
                 and r.ideal_rate > 0 and 0 <= r.good_units <= r.total_units
                 and r.total_units / r.ideal_rate <= r.run_minutes + 1e-6]
        planned = sum(r.planned_minutes for r in valid)
        run = sum(r.run_minutes for r in valid)
        ideal = sum(r.total_units / r.ideal_rate for r in valid)
        good = sum(r.good_units / r.ideal_rate for r in valid)
        def pct(a,b): return round(100*a/b,1) if b else None
        return dict(oee=pct(good,planned), availability=pct(run,planned), performance=pct(ideal,run),
                    quality=pct(good,ideal), output=sum(r.total_units for r in valid),
                    good_units=sum(r.good_units for r in valid), downtime=round(planned-run,1),
                    planned_minutes=round(planned,1), metric_records=len(valid))

    @app.get('/api/overview')
    def overview(building: str = 'all', days: int = Query(7, ge=1, le=30), user=Depends(current_user)):
        now = utcnow()
        start = now.date() - timedelta(days=days-1)
        with sessions() as db:
            q = select(Machine, Building.name).join(Building).order_by(Building.name, Machine.name)
            if '*' not in user['machines']:
                q = q.where(Machine.id.in_(user['machines']))
            pairs = list(db.execute(q))
            groups = {m.building_id:name for m,name in pairs}
            if building != 'all' and building not in groups:
                raise HTTPException(404, 'Building not available.')
            ids = [m.id for m,_ in pairs if building == 'all' or m.building_id == building]
            daily = list(db.scalars(select(DailyMetric).where(DailyMetric.machine_id.in_(ids), DailyMetric.day >= start, DailyMetric.day <= now.date())))
            by_machine = defaultdict(list)
            by_day = defaultdict(list)
            for row in daily:
                by_machine[row.machine_id].append(row)
                by_day[row.day].append(row)
            cards = []
            for m,name in pairs:
                if m.id not in ids: continue
                last = db.scalar(select(Reading).where(Reading.machine_id==m.id, Reading.recorded_at<=now).order_by(desc(Reading.recorded_at),desc(Reading.id)).limit(1))
                stale = last is None or (now-last.recorded_at).total_seconds() > settings.stale_seconds
                status = 'offline' if stale else reading_dict(last)['status']
                cards.append(dict(id=m.id,name=m.name,line=m.line,building_id=m.building_id,building=name,collection_mode=m.collection_mode,
                    status=status,last_update=iso(last.recorded_at) if last else None, rate=last.units_per_min if last and not stale else None,
                    metrics=kpis(by_machine[m.id])))
            buildings = []
            for bid,name in groups.items():
                scope = [m for m in cards if m['building_id']==bid]
                if not scope: continue
                counts = {s:sum(m['status']==s for m in scope) for s in ('running','warning','stopped','not_scheduled','offline','unknown')}
                buildings.append(dict(id=bid,name=name,count=len(scope),counts=counts,metrics=kpis([r for r in daily if r.machine_id in {m['id'] for m in scope}])) )
            losses = db.execute(select(Loss.reason, func.sum(Loss.minutes)).where(Loss.machine_id.in_(ids),Loss.day>=start,Loss.day<=now.date()).group_by(Loss.reason).order_by(desc(func.sum(Loss.minutes)))).all()
            trend = [dict(day=(start+timedelta(days=i)).isoformat(), **kpis(by_day[start+timedelta(days=i)])) for i in range(days)]
            return dict(generated_at=iso(now),days=days,building=building,buildings=buildings,available_buildings=[dict(id=i,name=n) for i,n in groups.items()],machines=cards,
                        metrics=kpis(daily),trend=trend,losses=[dict(reason=r,minutes=round(v,1)) for r,v in losses],demo=settings.demo)

    @app.get('/api/machines/{machine_id}/metrics')
    def machine_metrics(machine_id: str, days: int = Query(7, ge=1, le=30), user=Depends(current_user)):
        if not permitted(user,machine_id): raise HTTPException(403,'You do not have access to this machine.')
        today=utcnow().date()
        with sessions() as db:
            if not db.get(Machine,machine_id): raise HTTPException(404,'Machine not found.')
            start=today-timedelta(days=days-1)
            rows=list(db.scalars(select(DailyMetric).where(DailyMetric.machine_id==machine_id,DailyMetric.day>=start,DailyMetric.day<=today)))
            losses=db.execute(select(Loss.reason,func.sum(Loss.minutes)).where(Loss.machine_id==machine_id,Loss.day>=start,Loss.day<=today).group_by(Loss.reason).order_by(desc(func.sum(Loss.minutes)))).all()
            return dict(metrics=kpis(rows),losses=[dict(reason=r,minutes=round(v,1)) for r,v in losses],days=days)

    @app.get('/api/reports')
    def reports(building: str='all', days: int=Query(7,ge=1,le=30), user=Depends(current_user)):
        if user['role'] not in ('engineer','admin','supervisor'):
            raise HTTPException(403,'Reporting requires engineering access.')
        return overview(building,days,user)

    return app
