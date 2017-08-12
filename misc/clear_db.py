from birdseye.db import Function, Call, engine

for model in [Function, Call]:
    model.__table__.drop(engine)
