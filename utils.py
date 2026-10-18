
def read_file(path):
    try:
        with open(path, 'r') as file:
            return file.read()
    except FileNotFoundError:
        return ''


def write_file(path, content):
    with open(path, 'w') as file:
        file.write(content)


def append_to_file(path, content):
    with open(path, 'a') as file:
        file.write(f"{content}\n")


def increment_counter(path, step=1):
    try:
        with open(path, 'r+') as file:
            content = file.read().strip()
            value = int(content) if content.isdigit() else 0
            value += step
            file.seek(0)
            file.write(str(value))
            file.truncate()
            return value
    except FileNotFoundError:
        value = step if step > 0 else 0
        write_file(path, str(value))
        return value
