"""Study Buddy core logic: tasks, exams, quizzes, AI explanations.
Storage: JSON file by default, DynamoDB when TABLE_NAME is set.
AI: Amazon Bedrock (Converse API) when BEDROCK_MODEL_ID is set, else a static fallback.
"""
import os, json, datetime, threading

TABLE = os.environ.get("TABLE_NAME")
MODEL = os.environ.get("BEDROCK_MODEL_ID")
DATA_FILE = os.environ.get("DATA_FILE", "data.json")
_lock = threading.Lock()

def _blank(): return {"tasks": [], "exams": {}, "quiz": None, "stats": {"right": 0, "total": 0}}

def load(uid):
    with _lock:
        if TABLE:
            import boto3
            item = boto3.resource("dynamodb").Table(TABLE).get_item(Key={"userId": uid}).get("Item")
            return json.loads(item["data"]) if item else _blank()
        try:
            return json.load(open(DATA_FILE)).get(uid) or _blank()
        except (FileNotFoundError, ValueError):
            return _blank()

def save(uid, data):
    with _lock:
        if TABLE:
            import boto3
            boto3.resource("dynamodb").Table(TABLE).put_item(Item={"userId": uid, "data": json.dumps(data)})
            return
        try:
            all_ = json.load(open(DATA_FILE))
        except (FileNotFoundError, ValueError):
            all_ = {}
        all_[uid] = data
        json.dump(all_, open(DATA_FILE, "w"))

# ---------- AI ----------
def explain_topic(uid, topic):
    if MODEL:
        try:
            import boto3
            r = boto3.client("bedrock-runtime").converse(
                modelId=MODEL,
                system=[{"text": "You are a friendly study tutor on a voice assistant. Answer in at most 3 short "
                                 "spoken sentences. No lists, markdown or symbols."}],
                messages=[{"role": "user", "content": [{"text": "Explain: " + topic}]}],
                inferenceConfig={"maxTokens": 200})
            return r["output"]["message"]["content"][0]["text"]
        except Exception as e:
            print("Bedrock error:", e)
    return ("(Offline mode, no AI model configured.) Tip: break '%s' into smaller parts and explain "
            "each one in your own words." % topic)

# ---------- tasks ----------
def add_task(uid, task):
    d = load(uid); d["tasks"].append(task); save(uid, d)
    n = len(d["tasks"])
    return "Added %s. You now have %d task%s." % (task, n, "" if n == 1 else "s")

def list_tasks(uid):
    d = load(uid)
    if not d["tasks"]:
        return "Your study list is empty. Add a task to start."
    return "Your tasks are: " + ", ".join("%d, %s" % (i + 1, t) for i, t in enumerate(d["tasks"])) + "."

def complete_task(uid, task):
    t = task.lower(); d = load(uid)
    for i, x in enumerate(d["tasks"]):
        if t in x.lower() or x.lower() in t:
            d["tasks"].pop(i); save(uid, d)
            return "Nice work! I marked %s as done. %d left." % (x, len(d["tasks"]))
    return "I couldn't find that task. Ask me to list your tasks."

# ---------- exams ----------
def days_until(date_str):
    try:
        return (datetime.date.fromisoformat(date_str) - datetime.date.today()).days
    except (ValueError, TypeError):
        return None

def set_exam(uid, subject, date):
    n = days_until(date)
    if n is None:
        return "Please give the date as YYYY-MM-DD."
    d = load(uid); d["exams"][subject.lower()] = date; save(uid, d)
    return "Saved your %s exam.%s" % (subject, " That's in %d days." % n if n >= 0 else "")

def next_exam(uid):
    d = load(uid)
    up = sorted((days_until(v), k) for k, v in d["exams"].items() if days_until(v) is not None and days_until(v) >= 0)
    if not up:
        return "You have no upcoming exams saved."
    n, s = up[0]
    return "Your next exam is %s, %s." % (s, "today" if n == 0 else "tomorrow" if n == 1 else "in %d days" % n)

# ---------- quiz ----------
BANK = {
    "biology": [("Which organelle produces most of the cell's energy?", ["mitochondria", "mitochondrion"]),
                ("What molecule carries genetic information?", ["dna"]),
                ("What gas do plants absorb for photosynthesis?", ["carbon dioxide", "co2"])],
    "physics": [("What is the SI unit of force?", ["newton", "newtons"]),
                ("Which law says force equals mass times acceleration?", ["second law", "newton's second", "newtons second"]),
                ("What is the SI unit of energy?", ["joule", "joules"])],
    "computer science": [("What does CPU stand for?", ["central processing unit"]),
                         ("Which data structure is first in, first out?", ["queue"]),
                         ("What is the time complexity of binary search?", ["log n", "logarithmic", "o log n"])],
    "maths": [("What is the derivative of x squared?", ["2x", "two x"]),
              ("What is pi to two decimal places?", ["3.14", "3 point 14", "three point one four"]),
              ("What is the square root of 144?", ["12", "twelve"])],
}
QUIZ_LEN = 3

def start_quiz(uid, subject="computer science"):
    s = subject.lower()
    if s not in BANK:
        return "I have quizzes for: " + ", ".join(BANK) + "."
    d = load(uid); d["quiz"] = {"subject": s, "n": 0, "score": 0}; save(uid, d)
    return "Starting a %s quiz. Question 1. %s" % (s, BANK[s][0][0])

def answer_quiz(uid, answer):
    d = load(uid); q = d.get("quiz")
    if not q:
        return "No quiz running. Say: quiz me on biology."
    qs = BANK[q["subject"]]; question, keys = qs[q["n"]]
    ok = any(k in answer.lower() for k in keys)
    q["score"] += int(ok); q["n"] += 1
    st = d["stats"]; st["right"] += int(ok); st["total"] += 1
    fb = "Correct!" if ok else "Not quite. The answer is %s. %s" % (keys[0], explain_topic(uid, question + " Answer: " + keys[0]))
    if q["n"] >= QUIZ_LEN:
        score = q["score"]; d["quiz"] = None; save(uid, d)
        return "%s Quiz done. You scored %d out of %d. Overall you've answered %d of %d correctly." % (fb, score, QUIZ_LEN, st["right"], st["total"])
    save(uid, d)
    return "%s Question %d. %s" % (fb, q["n"] + 1, qs[q["n"]][0])
