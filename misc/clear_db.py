from birdseye.db import Function, Call, engine

for model in [Call, Function]:
    model.__table__.drop(engine)
