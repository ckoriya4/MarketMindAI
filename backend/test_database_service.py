
from services.database import test_database

try:
    database = test_database()
    print("Shared database service working!")
    print("Connected database:", database)

except Exception as error:
    print("Database service error:", error)
