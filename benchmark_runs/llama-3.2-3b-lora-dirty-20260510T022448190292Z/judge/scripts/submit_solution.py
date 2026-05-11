import argparse
import pymysql
import re
import os
from tqdm import tqdm
import json

language_name=["C","C++","Pascal","Java","Ruby","Bash","Python","PHP","Perl","C#","Obj-C","FreeBasic","Scheme","Clang","Clang++","Lua","JavaScript","Go","SQL","Fortran","Matlab","Cobol","UnknownLanguage"]

config_path = "/home/judge/etc/judge.conf"
virtual_path = "/var/www/virtual/"

# Function to extract value from config file
def get_config_value(keyword):
    with open(config_path, 'r') as config_file:
        for line in config_file:
            if keyword in line:
                return re.search(r'=(.*)', line).group(1).strip()

# Extracting values from config file
server = get_config_value('OJ_HOST_NAME')
user = get_config_value('OJ_USER_NAME')
password = get_config_value('OJ_PASSWORD')
database = get_config_value('OJ_DB_NAME')
port = int(get_config_value('OJ_PORT_NUMBER'))
mysql_command = "mysql -h {} -P {} -u {} -p{} {}".format(server, port, user, password, database)
print(mysql_command)
conn = pymysql.connect(host=server, port=port, user=user, password=password, database=database)
cursor = conn.cursor()

source_dir="/home/judge/log/new_outputs"
datadir="/home/judge/data"
solution_root="/home/judge/solution_folder/processed_solution"
SOURCE_COLUMN_TARGET_TYPE = "MEDIUMTEXT"
MAX_SOURCE_BYTES = (1 << 24) - 1


def normalize_source(source):
    if isinstance(source, list):
        return "\n".join("" if part is None else str(part) for part in source)
    if source is None:
        return None
    if isinstance(source, str):
        return source
    return str(source)


def source_size_bytes(source):
    return len(source.encode("utf-8"))


def ensure_source_column_capacity():
    try:
        cursor.execute(
            """
            SELECT DATA_TYPE
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'source_code' AND COLUMN_NAME = 'source'
            """,
            (database,),
        )
        row = cursor.fetchone()
        if not row:
            raise RuntimeError("Could not inspect source_code.source column metadata")
        current_type = row[0].lower()
        if current_type in ("tinytext", "text"):
            print(f"Upgrading source_code.source from {current_type} to {SOURCE_COLUMN_TARGET_TYPE}")
            cursor.execute(f"ALTER TABLE source_code MODIFY source {SOURCE_COLUMN_TARGET_TYPE} NOT NULL")
        elif current_type not in ("mediumtext", "longtext"):
            print(f"Leaving source_code.source unchanged with type={current_type}")
    except Exception as exc:
        print(f"Warning: could not adjust source_code.source column: {exc}")


def delete_partial_submission(solution_id):
    cursor.execute("DELETE FROM source_code WHERE solution_id = %s", (solution_id,))
    cursor.execute("DELETE FROM solution WHERE solution_id = %s", (solution_id,))


def parse_args():
    parser = argparse.ArgumentParser(description="Submit processed CodeEditorBench solutions into the judge DB.")
    parser.add_argument(
        "--model-name",
        action="append",
        default=[],
        help="Only submit specific processed solution files. May be passed multiple times.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    selected_model_names = set(args.model_name)
    ensure_source_column_capacity()

    for fname in os.listdir(solution_root):
        if not fname.endswith(".jsonl"):
            continue
        model_basename = fname[:-6]
        if selected_model_names and model_basename not in selected_model_names:
            continue
        solution_dir=os.path.join(solution_root,fname)
        with open(solution_dir,"r") as f:
            user_id="admin"
            skipped_rows = 0
            try:
                for count,line in tqdm(enumerate(f)):
                    if not line.strip():
                        continue
                    if count==0:
                        modelData = json.loads(line)
                        modelName = modelData['model_name']
                        modelSize = modelData.get('model_size',0)
                        greedy_search_decoding = modelData.get('greedy_search_decoding', 'N')
                        modelUrl = modelData.get('model_url',"")
                        doSample = modelData.get('do_sample', 'N')
                        temperature = modelData.get('temperature', 0.0)

                        sql = "SELECT `model_id` FROM `models` WHERE `model_name`=%s"
                        cursor.execute(sql, (modelName,))
                        result = cursor.fetchall()
                        if len(result)!=0:
                            print("skip existing model:",modelName)
                            break

                        try:
                            modelInsertQuery = "INSERT INTO models (user_id, model_name, size, model_url, greedy_search_decoding, do_sample, temperature) VALUES (%s,%s,%s,%s,%s,%s,%s)"
                            cursor.execute(modelInsertQuery, (user_id,modelName,modelSize,modelUrl, greedy_search_decoding, doSample, temperature,))
                            print(modelInsertQuery)
                            model_id = cursor.lastrowid
                            print("model_id",model_id)
                        except Exception as e:
                            print(e)
                            raise Exception("Invalid Meta data")
                    else:
                        solutionData=json.loads(line)
                        if solutionData is not None:
                            try:
                                skip_reason = solutionData.get("skip_submission_reason")
                                if skip_reason:
                                    print(f"Skipping {model_basename} row {count}: {skip_reason}")
                                    skipped_rows += 1
                                    continue
                                problemId = solutionData['problem_id']
                                source = normalize_source(solutionData['code'])
                                completion_id = solutionData['completion_id']
                                if source is None:
                                    continue
                                source_bytes = source_size_bytes(source)
                                if source_bytes > MAX_SOURCE_BYTES:
                                    print(
                                        f"Skipping problem_id={problemId} completion_id={completion_id} "
                                        f"because source is {source_bytes} bytes (> {MAX_SOURCE_BYTES})"
                                    )
                                    skipped_rows += 1
                                    continue
                                length = len(source)
                                language = solutionData['language']
                                try:
                                    lang = language_name.index(language)
                                except ValueError:
                                    print(f"The language {language} is not supported.")
                                    print("Supported languages are:")
                                    print(language_name)
                                    raise Exception("Invalid Language")

                                sql = "SELECT `contest_id`, `contest_name` FROM `problem` WHERE `problem_id`=%s"
                                cursor.execute(sql, (problemId,))
                                result = cursor.fetchall()
                                if len(result) == 0:
                                    raise Exception(f"Can't find corresponding contest of problem_id {problemId}")
                                contest_id = result[0][0]
                                contest_name = result[0][1]
                                num = None
                                inserttime=1
                                if contest_name == "code_debug":
                                    sql = "SELECT `id` FROM code_debug WHERE `problem_id`=%s"
                                elif contest_name == "code_translation":
                                    sql = "SELECT `id` FROM code_translation WHERE `problem_id`=%s"
                                elif contest_name == "code_polishment":
                                    sql = "SELECT `id` FROM code_polishment WHERE `problem_id`=%s"
                                    inserttime=2
                                elif contest_name == "code_requirement_switch":
                                    sql = "SELECT `id` FROM code_requirement_switch WHERE `problem_id`=%s"
                                else:
                                    raise Exception("Invalid contest_name")
                                cursor.execute(sql, (problemId,))
                                result = cursor.fetchall()
                                if result:
                                    num = result[0][0]
                                inserted_solution_ids = []
                                for _ in range(inserttime):
                                    # HUSTOJ's judged daemon dequeues rows with result < 2.
                                    # Insert new submissions as queued (0), not 14, or they never run.
                                    sql = "INSERT INTO solution(model_id, problem_id, completion_id, user_id, submit_date, language, code_length, contest_id, num, result) VALUES(%s, %s, %s, %s, NOW(), %s, %s, %s, %s, 0)"
                                    cursor.execute(sql, (model_id, problemId, completion_id, user_id, lang, length, contest_id, num))
                                    solution_id = cursor.lastrowid
                                    inserted_solution_ids.append(solution_id)
                                    try:
                                        codeInsertQuery = "INSERT INTO source_code (solution_id, source) VALUES (%s, %s)"
                                        cursor.execute(codeInsertQuery, (solution_id, source))
                                    except pymysql.err.DataError as e:
                                        if e.args and e.args[0] == 1406:
                                            for inserted_solution_id in inserted_solution_ids:
                                                delete_partial_submission(inserted_solution_id)
                                            print(
                                                f"Skipping problem_id={problemId} completion_id={completion_id} "
                                                f"after source insert overflow: {e}"
                                            )
                                            skipped_rows += 1
                                            inserted_solution_ids = []
                                            break
                                        raise
                                if not inserted_solution_ids:
                                    continue
                                sql = "UPDATE models SET submit = submit + 1 WHERE model_id = %s"
                                cursor.execute(sql, (model_id,))
                                sql = "UPDATE problem SET submit = submit + 1 WHERE problem_id = %s"
                                cursor.execute(sql, (problemId,))
                            except Exception as e:
                                print("Error:", str(e))
                                raise e
                conn.commit()
                if skipped_rows:
                    print(f"Skipped {skipped_rows} rows for {model_basename}")
            except Exception as e:
                conn.rollback()
                raise e

    cursor.close()
    conn.close()


if __name__ == "__main__":
    main()
