from .includes import *

"""
Event维护两张表：
1) 用户参与的事件
        由两个字段表示:
            1. events: list[ObjectId] 储存用户参加的事件的_id
            2. status: {_eid: { sign_in: datetime, sign_out: datetime }} 存储用户对某事件(_eid)的签到签退/参与情况
2) 事件报名的用户
        同样用两个字段记录报名与签到情况:
            1. roll: list[ObjectId] 存储事件的报名用户_id
            2. status: {_uid: {sign_in: datetime, sign_out: datetime }} 储存用户(_uid)对该事件的签到签退/参与情况

当事件需要签到签退的时候才存在 sign_in / sign_out, 否则以 status: bool 代替
"""

class Event:
    
    history = db.user_event_history
    event = db.event

    @classmethod
    async def get(cls, eid: str, uid: str = None):
        _eid = ObjectId(eid)
        if uid is not None:
            _uid = ObjectId(uid)
            rec = await cls.event.find_one({"_id": _eid})
            if not rec:
                raise ServiceException(status.HTTP_404_NOT_FOUND, detail='not found', code=ErrorCode.EVENT.NOT_FOUND)
            rec['joined'] = True if _uid in rec.get("roll", []) else False
            return rec
        rec = await cls.event.find_one({"_id": _eid}, {'roll': 0})
        return rec

    @classmethod
    async def list(cls, uid: str = None):
        if uid is None:
            return cls.event.find({})
        _uid = ObjectId(uid)
        return cls.event.aggregate([
            {
            "$project": {
                "title" : 1,
                "desc" : 1,
                'uid': 1,
                "organizer" : 1,
                "addr" : 1,
                "longtime" : 1,
                "range" : 1,
                "start": 1,
                "end": 1,
                "with_point" : 1,
                "point_detail" : 1,
                "with_reward" : 1,
                "reward_detail": 1,
                "limit_count" : 1,
                "max_count" : 1,
                "need_check": 1,
                "deadline": 1,
                "manual_stop": 1,
                'is_competition': 1,
                "joined": {
                    '$cond': [{
                        "$and": [
                            {"$gt": [{"$size": {"$ifNull": ["$roll", []]}}, 0]},
                            {"$in": [_uid, "$roll"]}
                        ]
                    }, True, False]
                }
            }
            },
            { "$sort": { '_id': -1 } }
        ])
    
    @classmethod
    async def create(cls, uid: str, event_form: EventCreateForm):
        _uid = ObjectId(uid)
        return await cls.event.insert_one({"uid": _uid, **event_form.dict(exclude_none=True)})

    @classmethod
    async def update(cls, id: str, form: EventCreateForm):
        await cls.event.update_one({"_id": ObjectId(id)}, {"$set": form.dict(exclude_none=True)})

    @classmethod
    async def if_stop(cls, id: str):
        _id = ObjectId(id)
        manual = await cls.event.find_one({"_id": _id}, {"manual_stop": 1, 'end': 1})
        now = datetime.now()
        manual_stop = manual.get('manual_stop', False)
        end = manual.get("end", None)
        if end:
            if now > end:
                return True
        return False
            
    @classmethod
    async def stop(cls, id: str):
        _id = ObjectId(id)
        # 检查是不是手动的
        manual = await cls.event.find_one({"_id": _id}, {"manual_stop": 1, 'end': 1})
        if not manual.get('manual_stop', False):
            raise ServiceException(status.HTTP_400_BAD_REQUEST, detail='非手动', code=ErrorCode.EVENT.IS_NOT_MANUAL_STOP)
        if manual.get("end", None) is not None:
            raise ServiceException(status.HTTP_400_BAD_REQUEST, detail='已停', code=ErrorCode.EVENT.HAS_STOPPED)
        return await cls.event.update_one({"_id": _id}, {
            "$set": {
                'end': datetime.now()
            }
        })
    
    @classmethod
    async def restart(cls, id: str):
        _id = ObjectId(id)
        # 检查是不是手动的
        manual = await cls.event.find_one({"_id": _id}, {"manual_stop": 1, 'end': 1})
        if not manual.get('manual_stop', False):
            raise ServiceException(status.HTTP_400_BAD_REQUEST, detail='非手动', code=ErrorCode.EVENT.IS_NOT_MANUAL_STOP)
        if manual.get("end", None) is None:
            raise ServiceException(status.HTTP_400_BAD_REQUEST, detail='没停止', code=ErrorCode.EVENT.NOT_STOP)
        return await cls.event.update_one({"_id": _id}, {
            "$unset": {
                'end': 1
            }
        })

    @classmethod
    async def get_joined_list(cls, uid: str, dtype=str):
        _uid = ObjectId(uid)
        user_hist = await cls.history.find({"uid": _uid}, {"eid": 1})
        hist = [i.get('eid') for i in user_hist]
        if dtype == str:
            return [str(h) for h in hist]
        elif dtype == ObjectId:
            return hist

    @classmethod
    async def join(cls, uid: str, eid: str):
        _uid = ObjectId(uid)
        _eid = ObjectId(eid)
        rec = await cls.event.find_one({"_id": _eid}, {
            "roll": 1,
            "limit_count": 1,
            "max_count": 1,
            "need_check": 1,
            "deadline": 1
        })

        if not rec:
            raise ServiceException(status.HTTP_404_NOT_FOUND, detail="event not found", code=ErrorCode.EVENT.NOT_FOUND)

        deadline = rec.get("deadline")
        if deadline < datetime.now():
            raise ServiceException(status.HTTP_403_FORBIDDEN, detail='截止', code=ErrorCode.EVENT.DEADLINE_HAS_PASSED)

        # 人数检测
        # TODO: redis 缓存事件人数
        roll = rec.get("roll", [])
        if rec.get('limit_count', False) and rec['max_count'] <= len(roll):
            raise ServiceException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="已满员", code=ErrorCode.EVENT.EXCEEDED_THE_UPPER_LIMIT)

        if _uid not in roll:
            # update event
            await cls.event.update_one({"_id": _eid}, {
                "$push": {
                    "roll": _uid
                },
                "$set": {
                    f"status.{uid}": {
                        'checkIn': None,
                        "checkOut": None
                    } if rec.get("need_check") else False
                }
            })
            # update history
            # *假设用户不在roll中就一定没有保存在history中
            await cls.history.insert_one({
                "uid": _uid,
                "eid": _eid,
                "status": {
                    'checkIn': None,
                    "checkOut": None
                } if rec.get("need_check") else False
            })
        else:
            raise ServiceException(status.HTTP_403_FORBIDDEN, detail='已报名了', code=ErrorCode.EVENT.HAS_JOINED)

    @classmethod
    async def exit(cls, uid: str, eid: str):
        _uid = ObjectId(uid)
        _eid = ObjectId(eid)
        
        rec = await cls.event.find_one({"_id": _eid}, {'roll': 1})
        if rec is None:
            raise ServiceException(status.HTTP_404_NOT_FOUND, detail='event not found', code=ErrorCode.EVENT.NOT_FOUND)
        roll = rec.get("roll", [])
        if _uid not in roll:
            raise ServiceException(
                status.HTTP_500_INTERNAL_SERVER_ERROR, 
                detail="user not joined", 
                code=ErrorCode.EVENT.NOT_JOINED
            )
        
        await cls.event.update_one({"_id": _eid}, {
            "$pull": {
                "roll": _uid
            },
            "$unset": {
                f"status.{uid}": ''
            }
        })
        await cls.history.delete_one({'uid': _uid, "eid": _eid})
