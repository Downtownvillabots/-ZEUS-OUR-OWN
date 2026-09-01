# database/db_manager.py
from database.ia_filterdb import DBS, MODELS, COLLECTIONS, db, db2, db3, Media, Media2, Media3

class DatabasePool:
    def __init__(self):
        self.databases = DBS
        self.models = MODELS
        self.collections = COLLECTIONS
        self.count = len(DBS)

    def get_database(self, index=0):
        return self.databases[index]

    def get_collection(self, index=0):
        return self.collections[index]

    def get_model(self, index=0):
        return self.models[index]

    def all_databases(self):
        return self.databases

    def all_collections(self):
        return self.collections

    def all_models(self):
        return self.models

    async def check_health(self):
        results = []
        for idx, d in enumerate(self.databases):
            try:
                await d.command('ping')
                results.append((idx, 'online'))
            except Exception as e:
                results.append((idx, f'error: {e}'))
        return results

_pool = None

def get_db_pool():
    global _pool
    if _pool is None:
        _pool = DatabasePool()
    return _pool