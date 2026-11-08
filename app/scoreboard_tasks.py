"""Fixed, automatically graded tasks for XemAi's model scoreboard.

All tasks are invented for XemAi (not copied from public benchmarks) so a model
can't pass them from memory. Every grade is objective: coding answers are run
against hidden tests; other answers are checked with explicit rules. The rules
are deliberately simple and visible here, so a score can always be explained.
"""

from __future__ import annotations

import json
import re

CATEGORIES = ("coding", "conversation", "facts", "instructions", "reasoning")

# ------------------------------------------------------------------- coding
# Each: function/class to write, the user prompt, and hidden tests (Python
# statements using `solution` namespace). Partial credit = fraction passed.

CODING = [
    {
        "id": "code-duration",
        "prompt": "Write a Python function parse_duration(text) that converts strings like '1h30m', '45s', "
                  "'2h' or '1h2m3s' into a total number of seconds (int). Units are h, m, s, each at most once, "
                  "in that order. Raise ValueError for anything else (including an empty string).",
        "tests": [
            "assert parse_duration('1h30m') == 5400",
            "assert parse_duration('45s') == 45",
            "assert parse_duration('2h') == 7200",
            "assert parse_duration('1h2m3s') == 3723",
            "raises(ValueError, parse_duration, '')",
            "raises(ValueError, parse_duration, '5x')",
            "raises(ValueError, parse_duration, '3m1h')",
        ],
    },
    {
        "id": "code-intervals",
        "prompt": "Write a Python function merge_intervals(intervals) that takes a list of [start, end] pairs "
                  "(ints, start <= end, any order) and returns a new list of merged, non-overlapping intervals "
                  "sorted by start. Intervals that touch (e.g. [1,3] and [3,5]) should merge.",
        "tests": [
            "assert merge_intervals([[1,3],[2,6],[8,10],[15,18]]) == [[1,6],[8,10],[15,18]]",
            "assert merge_intervals([[1,4],[4,5]]) == [[1,5]]",
            "assert merge_intervals([[5,7],[1,2]]) == [[1,2],[5,7]]",
            "assert merge_intervals([]) == []",
            "assert merge_intervals([[1,10],[2,3],[4,5]]) == [[1,10]]",
        ],
    },
    {
        "id": "code-roman",
        "prompt": "Write a Python function roman_to_int(s) that converts a valid Roman numeral string "
                  "(I, V, X, L, C, D, M with subtractive forms like IV and CM) to an integer.",
        "tests": [
            "assert roman_to_int('III') == 3",
            "assert roman_to_int('IV') == 4",
            "assert roman_to_int('MCMXCIV') == 1994",
            "assert roman_to_int('LVIII') == 58",
            "assert roman_to_int('MMXXVI') == 2026",
        ],
    },
    {
        "id": "code-topwords",
        "prompt": "Write a Python function top_k_words(text, k) returning the k most frequent words in text as a "
                  "list. Words are runs of letters a-z (case-insensitive, return lowercase). Ties are broken "
                  "alphabetically. If there are fewer than k distinct words, return them all.",
        "tests": [
            "assert top_k_words('the cat and the hat and the bat', 2) == ['the', 'and']",
            "assert top_k_words('B a b A c', 2) == ['a', 'b']",
            "assert top_k_words('one', 3) == ['one']",
            "assert top_k_words('Hello, hello! World.', 1) == ['hello']",
            "assert top_k_words('', 2) == []",
        ],
    },
    {
        "id": "code-brackets",
        "prompt": "Write a Python function brackets_balanced(s) returning True if every (, [ and { in s is closed "
                  "by the matching bracket in the correct order, ignoring all other characters, else False.",
        "tests": [
            "assert brackets_balanced('f(a[1]) {ok}') is True",
            "assert brackets_balanced('([)]') is False",
            "assert brackets_balanced('') is True",
            "assert brackets_balanced('((') is False",
            "assert brackets_balanced('}{') is False",
        ],
    },
    {
        "id": "code-rle",
        "prompt": "Write a Python function rle(s) that run-length encodes a string as count followed by character, "
                  "e.g. rle('aaabcc') == '3a1b2c'. rle('') == ''.",
        "tests": [
            "assert rle('aaabcc') == '3a1b2c'",
            "assert rle('') == ''",
            "assert rle('z') == '1z'",
            "assert rle('aaaaaaaaaaaab') == '12a1b'",
            "assert rle('abab') == '1a1b1a1b'",
        ],
    },
    {
        "id": "code-lru",
        "prompt": "Write a Python class LRUCache with __init__(self, capacity), get(self, key) returning the value or "
                  "-1 if missing, and put(self, key, value). When full, put evicts the least recently used key. "
                  "Both get and put count as a use.",
        "tests": [
            "c = LRUCache(2); c.put(1, 1); c.put(2, 2); assert c.get(1) == 1",
            "c = LRUCache(2); c.put(1, 1); c.put(2, 2); c.get(1); c.put(3, 3); assert c.get(2) == -1",
            "c = LRUCache(2); c.put(1, 1); c.put(2, 2); c.get(1); c.put(3, 3); assert c.get(1) == 1 and c.get(3) == 3",
            "c = LRUCache(1); c.put(1, 1); c.put(1, 5); assert c.get(1) == 5",
            "c = LRUCache(2); assert c.get(9) == -1",
        ],
    },
    {
        "id": "code-flatten",
        "prompt": "Write a Python function flatten(items) that takes a list which may contain nested lists or tuples "
                  "to any depth and returns a flat list of the non-list, non-tuple values in order. Strings are "
                  "values, not sequences to flatten.",
        "tests": [
            "assert flatten([1, [2, [3, (4, 5)]], 6]) == [1, 2, 3, 4, 5, 6]",
            "assert flatten([]) == []",
            "assert flatten(['ab', ['cd']]) == ['ab', 'cd']",
            "assert flatten([[[[]]], 7]) == [7]",
        ],
    },
    {
        "id": "code-weekday",
        "prompt": "Write a Python function next_weekday(date_str, weekday) where date_str is 'YYYY-MM-DD' and weekday "
                  "is a day name like 'monday' (any case). Return the date string of the next such weekday strictly "
                  "after date_str.",
        "tests": [
            "assert next_weekday('2026-11-08', 'monday') == '2026-11-09'",
            "assert next_weekday('2026-11-09', 'Monday') == '2026-11-16'",
            "assert next_weekday('2026-12-30', 'friday') == '2027-01-01'",
            "assert next_weekday('2024-02-28', 'thursday') == '2024-02-29'",
        ],
    },
    {
        "id": "code-spiral",
        "prompt": "Write a Python function spiral(matrix) that returns the elements of a rectangular list-of-lists "
                  "matrix in clockwise spiral order starting at the top-left.",
        "tests": [
            "assert spiral([[1,2,3],[4,5,6],[7,8,9]]) == [1,2,3,6,9,8,7,4,5]",
            "assert spiral([[1,2,3,4],[5,6,7,8]]) == [1,2,3,4,8,7,6,5]",
            "assert spiral([[1],[2],[3]]) == [1,2,3]",
            "assert spiral([]) == []",
        ],
    },
    {
        "id": "code-bugfix",
        "prompt": "This function should return the average of the positive numbers in a list, or 0.0 if there are "
                  "none, but it is buggy. Return the fixed function.\n\n```python\ndef average_positive(nums):\n"
                  "    total = 0\n    for n in nums:\n        if n >= 0:\n            total += n\n"
                  "    return total / len(nums)\n```",
        "tests": [
            "assert average_positive([1, 2, 3]) == 2.0",
            "assert average_positive([-5, 4, 6]) == 5.0",
            "assert average_positive([0, 2]) == 2.0",
            "assert average_positive([]) == 0.0",
            "assert average_positive([-1, -2]) == 0.0",
        ],
    },
    {
        "id": "code-anagrams",
        "prompt": "Write a Python function group_anagrams(words) that groups words that are anagrams of each other. "
                  "Return a list of groups; sort the words inside each group, and sort the groups by their first word.",
        "tests": [
            "assert group_anagrams(['eat','tea','tan','ate','nat','bat']) == [['ate','eat','tea'],['bat'],['nat','tan']]",
            "assert group_anagrams([]) == []",
            "assert group_anagrams(['a']) == [['a']]",
            "assert group_anagrams(['ab','ba','abc']) == [['ab','ba'],['abc']]",
        ],
    },
]

# ------------------------------------------------------------- conversation
# Multi-turn. `must` patterns must all match; `must_not` must not match.

CONVERSATION = [
    {
        "id": "conv-reference",
        "messages": [
            {"role": "user", "content": "I'm choosing between three laptops: the Aspire 5, the ZenBook 14 and the ThinkPad E14."},
            {"role": "assistant", "content": "Happy to help. What will you mainly use it for?"},
            {"role": "user", "content": "Mostly programming. Tell me more about the second one."},
        ],
        "must": [r"zenbook"],
    },
    {
        "id": "conv-correction",
        "messages": [
            {"role": "user", "content": "Give me three dinner ideas for this week."},
            {"role": "assistant", "content": "1. Chicken stir-fry\n2. Beef chilli\n3. Salmon with roast vegetables"},
            {"role": "user", "content": "Actually I'm vegetarian. Redo it."},
        ],
        "must": [r"\w{4,}"],
        "must_not": [r"\b(chicken|beef|pork|fish|tuna|salmon|bacon|ham|turkey|lamb|prawns?|shrimp|anchov\w*)\b"],
    },
    {
        "id": "conv-distractor",
        "system_extra": "BACKGROUND NOTE (not part of this conversation): an old example about planning a birthday "
                        "invitation for six guests and choosing the other venue option.",
        "messages": [{"role": "user", "content": "What's a good name for a grey cat?"}],
        "must": [r"\w{3,}"],
        "must_not": [r"birthday|guests?|invitation|venue"],
    },
    {
        "id": "conv-yes",
        "messages": [
            {"role": "user", "content": "It's 25 degrees Celsius outside."},
            {"role": "assistant", "content": "That's a warm day. Would you like me to convert that to Fahrenheit?"},
            {"role": "user", "content": "yes"},
        ],
        "must": [r"\b77\b"],
    },
    {
        "id": "conv-topic-switch",
        "messages": [
            {"role": "user", "content": "Which Skyrim mod manager should I use?"},
            {"role": "assistant", "content": "Vortex and Mod Organizer 2 are the two main choices; MO2 keeps your game folder clean."},
            {"role": "user", "content": "Unrelated, but how many tablespoons are in a US cup?"},
        ],
        "must": [r"\b16\b"],
        "must_not": [r"skyrim|vortex|mod organi[sz]er"],
    },
    {
        "id": "conv-name",
        "messages": [
            {"role": "user", "content": "Call me Sam from now on."},
            {"role": "assistant", "content": "Sure thing, Sam."},
            {"role": "user", "content": "Can you recommend a podcast about space?"},
            {"role": "assistant", "content": "Try 'StarTalk' for a fun mix of science and comedy."},
            {"role": "user", "content": "What's my name?"},
        ],
        "must": [r"\bsam\b"],
    },
    {
        "id": "conv-disagree",
        "messages": [{"role": "user", "content": "The Great Wall of China is visible from the Moon with the naked eye, right?"}],
        "must": [r"\b(no|not|isn't|myth|misconception|can't|cannot)\b"],
    },
    {
        "id": "conv-cheaper",
        "messages": [
            {"role": "user", "content": "I need to move house. What are my options?"},
            {"role": "assistant", "content": "Option A: rent a van for £80 and do it yourself. Option B: hire movers for £250."},
            {"role": "user", "content": "How much was the cheaper one?"},
        ],
        "must": [r"80"],
        "must_not": [r"\b250\b.*\bcheaper\b"],
    },
]

# ---------------------------------------------------------- facts & honesty

UNSURE = (r"(not (aware|familiar|able|sure)|no (record|information|reliable)|couldn't find|can't find|cannot find|"
          r"can't verify|cannot verify|unable to|doesn't appear|does not appear|don't have|do not have|"
          r"isn't a|not a real|may not exist|might not exist|no such|i'm not certain|can't confirm|cannot confirm)")

FACTS = [
    {"id": "fact-canberra", "messages": [{"role": "user", "content": "What is the capital of Australia?"}],
     "must": [r"canberra"]},
    {"id": "fact-bones", "messages": [{"role": "user", "content": "How many bones does an adult human have?"}],
     "must": [r"\b206\b"]},
    {"id": "fact-gold", "messages": [{"role": "user", "content": "What is the chemical symbol for gold?"}],
     "must": [r"\bAu\b"], "case_sensitive": True},
    {"id": "fact-austen", "messages": [{"role": "user", "content": "Who wrote Pride and Prejudice?"}],
     "must": [r"austen"]},
    {"id": "fact-km", "messages": [{"role": "user", "content": "How many metres are in a kilometre?"}],
     "must": [r"\b1,?000\b"]},
    {"id": "honest-einstein",
     "messages": [{"role": "user", "content": "Why did Albert Einstein win the Nobel Prize for his theory of relativity?"}],
     "must": [r"photoelectric"]},
    {"id": "honest-euro", "messages": [{"role": "user", "content": "When did the UK adopt the euro?"}],
     "must": [r"\b(never|didn't|did not|hasn't|has not|doesn't|does not|not adopt)\b"]},
    {"id": "honest-prime-one", "messages": [{"role": "user", "content": "Is 1 a prime number?"}],
     "must": [r"\b(no|not)\b"]},
    {"id": "honest-fake-book",
     "messages": [{"role": "user", "content": "Give me a summary of the 2017 novel 'The Lantern Keepers of Ossory Vale' by Margarethe Quill."}],
     "must": [UNSURE]},
    {"id": "honest-future",
     "messages": [{"role": "user", "content": "What will the exact closing value of the FTSE 100 be next Friday?"}],
     "must": [r"(can't|cannot|can not|unable to|impossible to|no way to|not possible to) (predict|know|tell|say|forecast|determine)"
              r"|(unpredictable|no one can (predict|know))"]},
]

# ---------------------------------------------------- instruction following

def _bullets(text: str) -> bool:
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    return len(lines) == 3 and all(re.match(r"^([-*•]|\d+[.)])\s+\S", l) for l in lines)


def _words_under(limit: int):
    return lambda text: 3 <= len(re.findall(r"\b[\w'-]+\b", text)) < limit


def _json_city(text: str) -> bool:
    body = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        data = json.loads(body)
    except ValueError:
        return False
    return (isinstance(data, dict) and set(data) == {"city", "country"}
            and str(data["city"]).lower() == "paris" and str(data["country"]).lower() == "france")


INSTRUCTIONS = [
    {"id": "inst-bullets", "messages": [{"role": "user", "content":
        "List exactly three benefits of walking as bullet points, with no introduction or conclusion."}],
     "check": _bullets},
    {"id": "inst-short", "messages": [{"role": "user", "content": "Describe the Moon in fewer than 25 words."}],
     "check": _words_under(25)},
    {"id": "inst-json", "messages": [{"role": "user", "content":
        "Reply with only a JSON object with exactly the keys \"city\" and \"country\" giving where the Eiffel Tower is."}],
     "check": _json_city},
    {"id": "inst-yesno", "messages": [{"role": "user", "content":
        "Answer with only the single word Yes or No: is the Pacific the largest ocean on Earth?"}],
     "check": lambda t: bool(re.fullmatch(r"\W*yes\W*", t.strip(), re.I))},
    {"id": "inst-lowercase", "messages": [{"role": "user", "content":
        "Write one sentence about rain, using only lowercase letters."}],
     "check": lambda t: bool(re.search(r"[a-z]{3}", t)) and not re.search(r"[A-Z]", t)},
    {"id": "inst-oneword", "messages": [{"role": "user", "content":
        "Give me one word that rhymes with 'cat'. Reply with that single word only."}],
     "check": lambda t: bool(re.fullmatch(r"\W*[a-z]*at\W*", t.strip(), re.I)) and t.strip(" .!*\"'").lower() != "cat"},
]

# --------------------------------------------------------------- reasoning

def _number(expected: float, tolerance: float = 1e-6):
    def check(text: str) -> bool:
        found = re.findall(r"-?\d+(?:[.,]\d+)?", text.replace(",", ""))
        return bool(found) and abs(float(found[-1]) - expected) <= tolerance
    return check


REASONING = [
    {"id": "math-pens", "messages": [{"role": "user", "content":
        "Pens cost £1.20 each. How much do 7 pens cost in pounds? End your reply with the number."}],
     "check": _number(8.4)},
    {"id": "math-train", "messages": [{"role": "user", "content":
        "A train leaves at 14:45 and the journey takes 2 hours 35 minutes. What time does it arrive (24-hour HH:MM)?"}],
     "check": lambda t: "17:20" in t},
    {"id": "math-percent", "messages": [{"role": "user", "content":
        "What is 17% of 240? End your reply with the number."}],
     "check": _number(40.8)},
    {"id": "math-eggs", "messages": [{"role": "user", "content":
        "I have 3 boxes with 12 eggs each and use 7 eggs. How many are left? End your reply with the number."}],
     "check": _number(29)},
    {"id": "math-perimeter", "messages": [{"role": "user", "content":
        "A rectangle is 8 cm by 5 cm. What is its perimeter in cm? End your reply with the number."}],
     "check": _number(26)},
    {"id": "logic-shortest", "messages": [{"role": "user", "content":
        "Sally is taller than Tom. Tom is taller than Ann. Who is the shortest?"}],
     "check": lambda t: bool(re.search(r"\bann\b", t, re.I)) and not re.search(r"\b(sally|tom) is the shortest", t, re.I)},
]


def all_tasks() -> list[dict]:
    tasks = []
    for item in CODING:
        tasks.append({**item, "category": "coding",
                      "messages": [{"role": "user", "content": item["prompt"] +
                                    "\nReply with the complete Python code in one ```python code block."}]})
    for group, name in ((CONVERSATION, "conversation"), (FACTS, "facts"),
                        (INSTRUCTIONS, "instructions"), (REASONING, "reasoning")):
        tasks.extend({**item, "category": name} for item in group)
    return tasks


def rule_score(task: dict, reply: str) -> float:
    """Score a non-coding reply 0 or 1 with the task's visible rules."""
    text = str(reply or "")
    if "check" in task:
        return 1.0 if task["check"](text) else 0.0
    flags = 0 if task.get("case_sensitive") else re.I
    if not all(re.search(p, text, flags) for p in task.get("must", [])):
        return 0.0
    if any(re.search(p, text, flags) for p in task.get("must_not", [])):
        return 0.0
    return 1.0
