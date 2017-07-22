from birdseye.app import Function, Call, db

for model in [Function, Call]:
    model.__table__.drop(db.engine)
