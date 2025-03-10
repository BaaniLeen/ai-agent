from pymongo import MongoClient
from datetime import datetime
import os
from typing import Dict, Any, Optional

class Database:
    def __init__(self):
        # Get MongoDB connection string from environment variable
        mongodb_uri = os.getenv("MONGODB_URI")
        if not mongodb_uri:
            raise ValueError("MONGODB_URI environment variable not set")
        
        self.client = MongoClient(mongodb_uri)
        self.db = self.client.habit_tracker
        self.users = self.db.users

    def get_user_data(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Retrieve user data from MongoDB"""
        return self.users.find_one({"_id": user_id})

    def create_user(self, user_id: int) -> Dict[str, Any]:
        """Create a new user document"""
        current_date = datetime.now().strftime("%Y-%m-%d")
        user_data = {
            "_id": user_id,
            "onboarded": False,
            "habit_goal": "",
            "milestones": [],
            "last_check_in": current_date,
            "reminder_time": "09:00",
            "current_streak": 0,
            "longest_streak": 0,
            "conversation_history": [],
            "progress_log": {}
        }
        self.users.insert_one(user_data)
        return user_data

    def update_user_data(self, user_id: int, update_data: Dict[str, Any]) -> None:
        """Update user data in MongoDB"""
        self.users.update_one(
            {"_id": user_id},
            {"$set": update_data}
        )

    def update_conversation_history(self, user_id: int, message: Dict[str, Any]) -> None:
        """Append a message to the user's conversation history"""
        self.users.update_one(
            {"_id": user_id},
            {"$push": {"conversation_history": message}}
        )

    def update_progress_log(self, user_id: int, date: str, entry: Dict[str, Any]) -> None:
        """Update the progress log for a specific date"""
        self.users.update_one(
            {"_id": user_id},
            {"$set": {f"progress_log.{date}": entry}}
        )

    def get_all_users(self):
        """Get all users for reminder checking"""
        return self.users.find({}) 