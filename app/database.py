from sqlalchemy import String, Float, Date, DateTime, Integer, ForeignKey, Index, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

class Base(DeclarativeBase):
    pass

class Building(Base):
    __tablename__ = "buildings"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))

class Machine(Base):
    __tablename__ = 'machines'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    line: Mapped[str] = mapped_column(String(120))
    building_id: Mapped[str] = mapped_column(ForeignKey("buildings.id"), index=True)
    collection_mode: Mapped[str] = mapped_column(String(24), default="automatic")
    ideal_rate: Mapped[float] = mapped_column(Float)

class Reading(Base):
    __tablename__ = 'sensor_readings'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    machine_id: Mapped[str] = mapped_column(ForeignKey('machines.id'))
    recorded_at: Mapped[object] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(24))
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    vibration_mm_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    motor_rpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    units_per_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    __table_args__ = (Index('ix_reading_machine_time', 'machine_id', 'recorded_at', 'id'),)


def make_database(url):
    opts = {'pool_pre_ping': True}
    if url.startswith('sqlite'):
        opts['connect_args'] = {'check_same_thread': False}
        if ':memory:' in url:
            opts['poolclass'] = StaticPool
    engine = create_engine(url, **opts)
    return engine, sessionmaker(engine, expire_on_commit=False)

class DailyMetric(Base):
    __tablename__ = 'daily_metrics'
    machine_id: Mapped[str] = mapped_column(ForeignKey('machines.id'), primary_key=True)
    day: Mapped[object] = mapped_column(Date, primary_key=True)
    planned_minutes: Mapped[float] = mapped_column(Float)
    run_minutes: Mapped[float] = mapped_column(Float)
    total_units: Mapped[int] = mapped_column(Integer)
    good_units: Mapped[int] = mapped_column(Integer)
    ideal_rate: Mapped[float] = mapped_column(Float)

class Loss(Base):
    __tablename__ = 'machine_losses'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    machine_id: Mapped[str] = mapped_column(ForeignKey('machines.id'), index=True)
    day: Mapped[object] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(String(120))
    minutes: Mapped[float] = mapped_column(Float)
    __table_args__ = (Index('ix_loss_machine_day', 'machine_id', 'day'),)
