from fastapi import HTTPException, status
# from pymongo import MongoClient
import motor.motor_asyncio
from pymongo import MongoClient
from bson.objectid import ObjectId

from .r import RedisProvider
from ..DataModel import *
from ..exceptions import ServiceException, ErrorCode

r = RedisProvider()
client = motor.motor_asyncio.AsyncIOMotorClient("mongodb://localhost:27017")
db = client.ITA