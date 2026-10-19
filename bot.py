import logging
import os
import time
from logging.handlers import RotatingFileHandler

import requests
from dotenv import load_dotenv
from requests.exceptions import HTTPError, RequestException

from utils import append_to_file, increment_counter, read_file, write_file

load_dotenv()

GITHUB_USER = os.getenv("GITHUB_USER")
PERSONAL_GITHUB_TOKEN = os.getenv("PERSONAL_GITHUB_TOKEN")

PER_PAGE = 100
FOLLOWERS_URL_TEMPLATE = "https://api.github.com/users/{}/followers"
FOLLOWING_URL = "https://api.github.com/user/following"
FOLLOW_USER_URL_TEMPLATE = "https://api.github.com/user/following/{}"
RATE_LIMIT_URL = "https://api.github.com/rate_limit"

FOLLOWED_USERS_FILE = "followers.txt"
FOLLOWER_COUNTER_FILE = "follower_counter.txt"
LAST_CHECKED_FOLLOWER_FILE = "last_checked_follower.txt"

RATE_LIMIT_THRESHOLD = 100
BATCH_SIZE = 30
BATCH_SLEEP_INTERVAL = 60
FOLLOW_DELAY_SECONDS = 2

logger = logging.getLogger("GitHubFollowerBot")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    file_handler = RotatingFileHandler("bot.log", maxBytes=5 * 1024 * 1024, backupCount=2)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)


def _headers():
    return {
        "Authorization": f"token {PERSONAL_GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }


def _followers_url(username=None):
    return FOLLOWERS_URL_TEMPLATE.format(username or GITHUB_USER)


def read_followed_users(path=FOLLOWED_USERS_FILE):
    content = read_file(path)
    return {line.strip() for line in content.splitlines() if line.strip()}


def check_rate_limit():
    try:
        response = requests.get(RATE_LIMIT_URL, headers=_headers())
        response.raise_for_status()
        core = response.json().get("resources", {}).get("core", {})
        remaining = core.get("remaining")
        reset_time = core.get("reset")
        return remaining, reset_time
    except RequestException as exc:
        logger.error("Failed to check rate limit: %s", exc)
        return None, None


def fetch_followers(url, page=1):
    try:
        response = requests.get(url, headers=_headers(), params={"page": page, "per_page": PER_PAGE})
        response.raise_for_status()
        return response.json()
    except RequestException as exc:
        logger.error("Failed to fetch followers from page %s: %s", page, exc)
        return []


def fetch_following(page=1):
    try:
        response = requests.get(FOLLOWING_URL, headers=_headers(), params={"page": page, "per_page": PER_PAGE})
        response.raise_for_status()
        return response.json()
    except RequestException as exc:
        logger.error("Failed to fetch following users from page %s: %s", page, exc)
        return []


def follow_user(username):
    url = FOLLOW_USER_URL_TEMPLATE.format(username)
    try:
        response = requests.put(url, headers=_headers())
        if response.status_code == 204:
            logger.info("Successfully followed user: %s", username)
            return True
        logger.warning("Failed to follow %s. Status Code: %s", username, response.status_code)
        return False
    except RequestException as exc:
        logger.error("RequestException while following %s: %s", username, exc)
        return False


def get_new_followers(last_checked_follower, all_followers):
    if not last_checked_follower:
        return all_followers
    try:
        index = all_followers.index(last_checked_follower)
        return all_followers[:index]
    except ValueError:
        return all_followers


def process_batch(usernames, followers_file=FOLLOWED_USERS_FILE, last_checked_file=LAST_CHECKED_FOLLOWER_FILE,
                  counter_file=FOLLOWER_COUNTER_FILE, follow_delay=FOLLOW_DELAY_SECONDS):
    for username in usernames:
        if follow_user(username):
            append_to_file(followers_file, username)
            write_file(last_checked_file, username)
            increment_counter(counter_file)
        if follow_delay:
            time.sleep(follow_delay)


def process_followers_in_batches(new_followers, batch_size=BATCH_SIZE, sleep_interval=BATCH_SLEEP_INTERVAL):
    for i in range(0, len(new_followers), batch_size):
        batch = new_followers[i:i + batch_size]
        process_batch(batch)
        if i + batch_size < len(new_followers):
            time.sleep(sleep_interval)


def _collect_all_follower_logins():
    followers_url = _followers_url()
    page = 1
    all_followers = []

    while True:
        followers = fetch_followers(followers_url, page=page)
        if not followers:
            break
        all_followers.extend([f.get("login") for f in followers if f.get("login")])
        if len(followers) < PER_PAGE:
            break
        page += 1

    return all_followers


def _collect_all_following_logins():
    page = 1
    all_following = []

    while True:
        following_users = fetch_following(page=page)
        if not following_users:
            break
        all_following.extend([u.get("login") for u in following_users if u.get("login")])
        if len(following_users) < PER_PAGE:
            break
        page += 1

    return set(all_following)


def main():
    if not GITHUB_USER or not PERSONAL_GITHUB_TOKEN:
        raise EnvironmentError("Please set both 'GITHUB_USER' and 'PERSONAL_GITHUB_TOKEN' in your environment variables.")

    logger.info("Starting follower sync for %s", GITHUB_USER)

    remaining, reset_time = check_rate_limit()
    if remaining is not None and remaining < RATE_LIMIT_THRESHOLD and reset_time:
        sleep_duration = max(reset_time - int(time.time()), 1)
        logger.warning("Low rate limit (%s), sleeping %s seconds", remaining, sleep_duration)
        time.sleep(sleep_duration)

    all_followers = _collect_all_follower_logins()
    currently_following = _collect_all_following_logins()
    remaining_followers = [user for user in all_followers if user not in currently_following]

    if not remaining_followers:
        logger.info("No new followers to process.")
        return

    process_followers_in_batches(remaining_followers)

    total_followed = increment_counter(FOLLOWER_COUNTER_FILE, step=0)
    logger.info(
        "Follower sync complete. Total followers fetched: %s, already followed: %s, pending processed: %s, counter: %s",
        len(all_followers),
        len(currently_following),
        len(remaining_followers),
        total_followed,
    )


if __name__ == "__main__":
    main()
