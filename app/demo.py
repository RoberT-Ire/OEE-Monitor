from datetime import datetime, timedelta, timezone
import math
import random
from sqlalchemy import delete
from .database import Base, Building, Machine, Reading, DailyMetric, Loss

# Illustrative grouping only; these are not verified site assignments.
BUILDINGS = [('liquid','Large Liquid'), ('cpml','CPML 2'), ('blister','Blister'), ('solid','Solid'), ('realoch','Realoch')]
MACHINES = [
 ('BOT-01','Bottling line 1','Line 01','liquid',130,'automatic'),
 ('LAB-02','Liquid labeller','Line 02','liquid',120,'automatic'),
 ('PKG-03','Liquid filling line 4','Line 04','liquid',150,'automatic'),
 ('CP-01','Pack Room 1','Line 01','cpml',110,'automatic'),
 ('CP-02','B Pack','Line 02','cpml',100,'automatic'),
 ('CP-03','Countec','Line 03','cpml',100,'manual'),
 ('BL-01','Blister Line 1','Line 01','blister',95,'automatic'),
 ('BL-05','Blister Line 5','Line 05','blister',95,'automatic'),
 ('SL-01','Tablet packing','Line 01','solid',110,'automatic'),
 ('SL-02','Solid Line 2','Line 02','solid',100,'manual'),
 ('RE-01','Volpack','Line 01','realoch',85,'automatic'),
 ('RE-02','Sarong','Line 02','realoch',85,'automatic'),
]

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

def simulated_reading(machine_id, t, index, now):
    minute = int(t.replace(tzinfo=timezone.utc).timestamp()) // 60
    age = (now-t).total_seconds()/60
    r = random.Random(minute * 17 + index)
    phase = (int(age) + index*19) % 137
    status = 'stopped' if 40 <= phase < 52 else ('warning' if 35 <= phase < 40 else 'running')
    if age < 18:
        status = ['running','warning','stopped','running','running','running','running','stopped','running','warning','not_scheduled','running'][index]
    running = status in ('running','warning')
    rate = round(MACHINES[index][4]*.88 + 5*math.sin(minute/7)+r.uniform(-3,3),1) if running else 0
    return Reading(machine_id=machine_id, recorded_at=t,status=status, temperature_c=round(41+index*.5+(8 if status=='warning' else 0)+r.uniform(-1,1),1), vibration_mm_s=round(2+r.random()*.7 if running else .2,2),motor_rpm=round(1450+r.uniform(-25,25)) if running else 0,units_per_min=rate)

def seed(engine, sessions):
    Base.metadata.create_all(engine)
    now = utcnow()
    with sessions.begin() as db:
        for bid,name in BUILDINGS:
            if db.get(Building,bid) is None: db.add(Building(id=bid,name=name))
        db.flush()
        for mid,name,line,bid,rate,mode in MACHINES:
            if db.get(Machine,mid) is None: db.add(Machine(id=mid,name=name,line=line,building_id=bid,ideal_rate=rate,collection_mode=mode))
        db.flush()
        for model in (Reading, DailyMetric, Loss): db.execute(delete(model))
        for i,(mid,_,_,_,rate,_) in enumerate(MACHINES):
            # Last 24 hours of readings; one machine intentionally has stale data.
            db.add_all(simulated_reading(mid,now-timedelta(minutes=m),i,now) for m in range(1440, 4 if i==11 else -1,-1))
            for offset in range(30):
                day = now.date()-timedelta(days=offset)
                rng = random.Random(day.toordinal()*33+i)
                planned = 480 if offset else 360
                if i==10 and offset==0: planned=0
                avail = min(.98,max(.48,.93-(i%4)*.075+rng.uniform(-.08,.08)))
                perf = min(.99,max(.60,.96-(i%5)*.045+rng.uniform(-.05,.05)))
                run = round(planned*avail,1)
                total = int(run*rate*perf)
                good = int(total*rng.uniform(.95,.995))
                db.add(DailyMetric(machine_id=mid,day=day,planned_minutes=planned,run_minutes=run,total_units=total,good_units=good,ideal_rate=rate))
                lost = round(planned-run,1)
                if lost:
                    reason = ['Batch changeover','Materials waiting','Labels snapping','Recorded stoppage'][i%4]
                    first=round(lost*.65,1)
                    db.add_all([Loss(machine_id=mid,day=day,reason=reason,minutes=first),Loss(machine_id=mid,day=day,reason='Planned break',minutes=round(lost-first,1))])

def tick(sessions):
    now=utcnow()
    with sessions.begin() as db:
        db.add_all(simulated_reading(mid,now,i,now) for i,(mid,*_) in enumerate(MACHINES) if i!=11)
        db.execute(delete(Reading).where(Reading.recorded_at < now-timedelta(hours=25)))
