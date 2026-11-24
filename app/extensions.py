from flask_sqlalchemy import SQLAlchemy
from flask_caching import Cache
from flask_migrate import Migrate

db = SQLAlchemy()
cache = Cache()
migrate = Migrate()
