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
            "fitness_goal": "",
            "starting_metrics": {},
            "experience_level": "",
            "limitations": "",
            "milestones": [],
            "last_check_in": current_date,
            "last_reminder_sent": current_date,
            "reminder_time": "20:00",
            "timezone": None,  # Added timezone field
            "current_streak": 0,
            "longest_streak": 0,
            "conversation_history": [],
            "progress_log": {},
            "rest_days": [],
            # New fields for workout tracking
            "exercise_history": {},  # Track performance for each exercise
            "current_workout": None,  # Store ongoing workout session
            "workout_sessions": [],  # Store completed workout sessions
            "max_weights": {},  # Track max weights for progressive overload
            "preferred_exercises": []  # Store exercises that work well for the user
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

    def delete_user(self, user_id: int) -> None:
        """Delete a user's data from the database"""
        self.users.delete_one({"_id": user_id})

    def update_exercise_history(self, user_id: int, exercise: str, performance: Dict[str, Any]) -> None:
        """Update the exercise history for a user"""
        date = datetime.now().strftime("%Y-%m-%d")
        self.users.update_one(
            {"_id": user_id},
            {"$push": {f"exercise_history.{exercise}": {
                "date": date,
                **performance
            }}}
        )

    def start_workout_session(self, user_id: int, workout_plan: Dict[str, Any]) -> None:
        """Start a new workout session"""
        self.users.update_one(
            {"_id": user_id},
            {"$set": {"current_workout": workout_plan}}
        )

    def complete_workout_session(self, user_id: int, session_data: Dict[str, Any]) -> None:
        """Complete a workout session and store the results"""
        self.users.update_one(
            {"_id": user_id},
            {
                "$push": {"workout_sessions": session_data},
                "$set": {"current_workout": None}
            }
        ) 