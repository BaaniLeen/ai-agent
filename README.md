# GrowthBuddy - AI Fitness Coach Discord Bot 🤖💪

An intelligent Discord bot powered by Mistral AI that serves as a personal fitness coach, helping users track workouts, maintain streaks, and achieve their fitness goals. The bot provides personalized workout plans, daily check-ins, and motivational support through natural conversation.

## Overview

This Discord bot combines the power of large language models with structured fitness tracking to create an engaging and effective fitness coaching experience. It helps users:

- Set and track fitness goals
- Generate personalized workout plans
- Maintain daily workout streaks
- Receive timely reminders
- Track progress over time
- Get form tips and exercise suggestions

## High-level Architecture 🏗️

![GrowBuddy](https://github.com/user-attachments/assets/1309b6be-2e53-4950-826e-00009ee9c37b)


### Core Components 🔧

1. **Discord Bot Layer**
   - Handles message routing and command processing
   - Manages Discord-specific functionality
   - Provides user interface through Discord

2. **Application Layer**
   - **AI Agent**: Orchestrates conversations and AI interactions
   - **Workflow Manager**: Handles user states and session management
   - **Command Handler**: Processes user commands and responses

3. **AI Services**
   - Integrates with Mistral AI for natural language processing
   - Generates personalized responses and workout plans
   - Provides contextual fitness advice

4. **Data Layer**
   - MongoDB for persistent storage
   - Tracks user progress and streaks
   - Stores conversation history and workout data

## Architecture

<img width="880" alt="Screenshot 2025-03-12 at 11 00 11 AM" src="https://github.com/user-attachments/assets/6a442392-31c4-434f-9b20-f86981132a52" />


## Getting Started 🚀

### Prerequisites

```bash
# Required software
- Python 3.8+
- MongoDB
- Discord Developer Account
```

### Environment Setup

1. Clone the repository:
```bash
git clone https://github.com/yourusername/ai-fitness-coach.git
cd ai-fitness-coach
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
```bash
# Create .env file
DISCORD_TOKEN=your_discord_token
MISTRAL_API_KEY=your_mistral_api_key
MONGODB_URI=your_mongodb_uri
```

4. Initialize the database:
```bash
python setup_db.py
```

### Running the Bot

```bash
python bot.py
```

## Features 🎯

### User Commands

- `!start_workout` - Begin an interactive workout session
- `!end_workout` - End an interactive workout session
- `!streak` - Check your current workout streak
- `!progress [days]` - View your workout history
- `!reminder HH:MM` - Set daily check-in time
- `!timezone` - Set your timezone for reminders
- `!reset` - Reset your fitness tracking data

### AI-Powered Interactions

- Natural conversation about fitness goals
- Personalized workout recommendations
- Form tips and exercise modifications
- Progress tracking and motivation
- Streak maintenance and celebrations

### Automated Features

- Daily check-in reminders
- Streak tracking
- Progress monitoring
- Timezone-aware scheduling
- Workout history logging

## Configuration ⚙️

### Discord Bot Settings

1. Enable required intents in Discord Developer Portal:
   - Message Content Intent
   - Server Members Intent
   - Presence Intent

2. Configure bot permissions:
   - Send Messages
   - Read Message History
   - Add Reactions
   - View Channels

### Database Configuration

1. MongoDB setup:
   - Create a database named 'fitness_bot'
   - Collections: users, workouts, progress

2. Update connection string in `.env`:
```bash
MONGODB_URI=mongodb://username:password@host:port/fitness_bot
```

## Development 👨‍💻

### Project Structure

```
ai-fitness-coach/
├── bot.py # Main Discord bot implementation
├── agent.py # MistralAgent implementation
├── database.py # Database operations
├── utils/
│ ├── constants.py # System prompts and constants
│ └── helpers.py # Utility functions
├── requirements.txt # Project dependencies
└── README.md # Project documentation
```


### Adding New Features

1. Create new command in `bot.py`:
```python
@commands.command()
async def new_command(self, ctx):
    # Implementation
```

2. Add database operations in `database.py`
3. Update AI prompts in `constants.py`
4. Test thoroughly before deployment

## Contributing 🤝

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Open a Pull Request

## License 📝

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments 🙏

- Mistral AI
- Help from Cursor! :)

## Support 💬

For support, please:
1. Check the documentation
2. Open an issue
3. Join our Discord community

---
