import subprocess
import sys
import io

try:
    import pandas as pd
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pandas"])
    import pandas as pd

try:
    import requests
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests


MONTHS_RU = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"
}

def load_sheet_from_google(sheet_id: str, gid: str) -> pd.DataFrame:
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
    response = requests.get(url)

    if response.status_code != 200:
        raise Exception(f"Ошибка загрузки: {response.status_code}")

    response.encoding = "utf-8"
    df = pd.read_csv(io.StringIO(response.text), header=None)
    return df

def is_work(value):
    if pd.isna(value):
        return False
    return str(value).strip() in ["1"]

def extract_day(date_value):
    try:
        return int(str(date_value).split()[0])
    except Exception:

        return None

def get_schedule_data(sheet_id: str, gid: str, month: int) -> dict:
    all_schedule = {}

    df = load_sheet_from_google(sheet_id, gid)

    name_row = df.iloc[1]

    # Старшие, идут первыми в списке people
    senior_cols = {}
    for col_idx in range(6, 9):
        if col_idx < len(name_row):
            name = str(name_row[col_idx]).strip()
            if name and name != "nan" and "Unnamed" not in name:
                senior_cols[col_idx] = name

    # обычные сотрудники
    regular_cols = {}
    for col_idx in range(9, 38):
        if col_idx < len(name_row):
            name = str(name_row[col_idx]).strip()
            if name and name != "nan" and "Unnamed" not in name:
                regular_cols[col_idx] = name

    STOP_TITLES = {"старший", "кол-во смен", "нужно людей", "итого", "смен на начало"}

    current_date = None

    for row_idx in range(3, len(df)):
        row = df.iloc[row_idx]

        title = row[2]
        scene = row[1]

        # остановка, если дошли до служебных строк
        if not pd.isna(title):
            if any(stop in str(title).strip().lower() for stop in STOP_TITLES):
                break
        if not pd.isna(scene):
            if any(stop in str(scene).strip().lower() for stop in STOP_TITLES):
                break

        # дата
        if not pd.isna(row[0]):
            day = extract_day(row[0])
            if day:
                current_date = f"{day} {MONTHS_RU[month]}"

        if not current_date:
            continue
        if pd.isna(title):
            continue

        title_clean = str(title).strip()
        if not title_clean:
            continue

        scene_clean = str(scene).strip() if not pd.isna(scene) else ""

        seniors = sorted([name for col_idx, name in senior_cols.items() if is_work(row[col_idx])])
        regulars = sorted([name for col_idx, name in regular_cols.items() if is_work(row[col_idx])])
        people = seniors + regulars

        if not people:
            continue

        if current_date not in all_schedule:
            all_schedule[current_date] = []

        all_schedule[current_date].append({
            "scene": scene_clean,
            "title": title_clean,
            "people": people  # старшие первые, остальные по алфавиту
        })

    return all_schedule


def get_actual_schedule() -> dict:

    # Чтобы сменить лист — надо менять current_gid и current_month

    sheet_id = "1B07yLkFHGKKdkXz9c1lmxcGZYjmD7gMKXFU9Ds-_Va0" # таблица
    current_gid = "876965220"  # Рабочие дни Апрель 26
    current_month = 4

    return get_schedule_data(sheet_id, current_gid, current_month)


#Тест
if __name__ == "__main__":
    data = get_actual_schedule()

    sorted_data = dict(sorted(data.items(), key=lambda x: int(x[0].split()[0])))

    for date, shows in sorted_data.items():
        print(f"\n{date.upper()}")
        for show in shows:
            print(f"\n{show['title']}")
            print(f"Сцена: {show['scene']}")
            print(f"Состав:")
            for person in show['people']:
                print(f"{person}")