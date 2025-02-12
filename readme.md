# Dev Life Organizer Bot

A personal Slack assistant that keeps track of your tasks, reminds you of important events, and automates routine actions.

## 🚀 Why Use This?
- **Structured Workday:** Manage tasks and reminders without leaving Slack.
- **Automation:** Automatically track tasks, code reviews, and standup updates.
- **Focus:** Reduce distractions and boost productivity by automating routine actions.

## Features
- **Daily Summary in the Morning**
  - Sends a morning summary of pending PR reviews and your to-do list.
- **Smart Code Review Reminders**
  - Notifies you when you have assigned PRs, pending reviews, or stale PRs.
- **Deep Work Mode (Slack Mute)**
  - Temporarily mutes notifications with an auto-reply message.
  - Automatically turns off after a set duration.
- **Quick To-Do List Inside Slack**
  - `/addtask Fix bug in login API` → Adds a new task.
  - `/listtask` → Displays all pending tasks.
  - `/marktaskdone <task_id>` → Marks a task as complete.
- **Automatic Standup Generator**
  - Tracks your GitHub commits and Jira tickets.
  - Suggests a standup update draft for you.
- **Smart Reminders for Breaks & Health**
  - Reminds you to take breaks, hydrate, or stretch throughout the day.

## 📌 Roadmap
- Daily Summary in the Morning
- Smart Code Review Reminders
- Deep Work Mode (Slack Mute)
- Quick To-Do List Inside Slack
- Automatic Standup Generator
- Smart Reminders for Breaks & Health

## 🔧 Installation

### Prerequisites
- **Python 3.7+**
- **Slack Workspace:** A Slack app must be created with the appropriate scopes and slash commands.
- **GitHub & Jira Accounts:** Ensure you have API access for integration.

### Steps

1. **Clone the Repository:**

   ```bash
   git clone https://github.com/AnujVijjan/DevLifeOrganizerBot.git
   cd DevLifeOrganizerBot
   ```

2. **Create and Activate a Virtual Environment:**

   ```bash
   python3 -m venv venv
   source venv/bin/activate   # On Windows: venv\Scripts\activate
   ```

3. **Install Dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

4. **Set Up Environment Variables:**

   Copy the provided `sample.env` file to `.env` and update it with your own configuration:

   ```bash
   cp sample.env .env
   ```

   The `sample.env` file contains placeholder values for:
   - Slack credentials
   - GitHub credentials (including branch names and search keywords)
   - Jira credentials

   **Make sure to update the values in `.env` before running the application.**

5. **Configure Your Slack App:**

   - **Manifest:** Use the included `manifest.json` file as a starting point.  
     **Important:** Replace any development URLs (such as ngrok URLs) with your own public endpoint if you're deploying in production.
   - **Setup:** Import the manifest in the Slack Developer Portal and complete any additional configuration (e.g., OAuth scopes, event subscriptions).
   - **Installation:** Install the app to your Slack workspace.

6. **Run the Application:**

   If you’re using Flask, for example, run:

   ```bash
   flask run
   ```

   Ensure that your app is reachable from the public internet (use a tunneling tool like ngrok during development).

## 🤝 Contributing
Contributions are welcome! Please open an issue or submit a pull request with your improvements or bug fixes.
