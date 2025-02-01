import configparser
import os
import signal
import subprocess
import sys
from functools import partial

# COLORS
RED = "\033[31m"
BRIGHT_RED = "\033[91m"
GREEN = "\033[32m"
BRIGHT_GREEN = "\033[92m"
MAGENTA = "\033[35m"
BRIGHT_BLUE = "\033[94m"

BOLD = "\033[1m"
RESET = "\033[0m"

cfg: configparser.ConfigParser = configparser.ConfigParser()
debug = False
testing = False
test_case_count = 0


def filter_filenames(name: str, allowed_ext: list[str]) -> bool:
    """Determine whether a filename has an allowed extension or not"""
    for ext in allowed_ext:
            if name.endswith(ext):
                return True
    return False


def run() -> None:
    global cfg

    success_count = 0
    fail_count = 0
    failed_cases: list[str] = []

    extensions = [f'.{ext.strip()}' for ext in cfg["paths"]["allowed_file_extensions"].split(",")]
    dbgprint("Extensions:", extensions)

    test_path = cfg["paths"]["input_dir"]
    dbgprint("Test Path:", test_path)
    for (dirpath, dirnames, filenames) in os.walk(test_path, topdown=True):
        dbgprint(dirpath, dirnames, filenames)
        # modify dirnames to exclude dotfiles
        if cfg["general"].getboolean("exclude_hidden_directories"):
            dirnames[:] = [d for d in dirnames if not d.startswith('.')]

        dir_success_count = 0
        dir_fail_count = 0
        # bind the allowed_ext parameter to a value so that we can pass to
            # filter()
        filter_func = partial(filter_filenames, allowed_ext=extensions)
        for filename in filter(filter_func, filenames):
            full_name = os.path.join(dirpath, filename)
            if testing:
                if test_file(full_name):
                    dir_success_count +=1
                else:
                    dir_fail_count +=1
                    if cfg["testing"].getboolean("verbose_names"):
                        failed_cases.append(full_name)
                    else:
                        failed_cases.append(gen_short_path(full_name))

            else: # just for executing, no testing
              run_file(full_name)

        if testing:
            # update "global" counters
            success_count += dir_success_count
            fail_count += dir_fail_count

            # display local stats
            if dir_success_count == 0 or dir_fail_count == 0:
                continue
            perc_color = GREEN if dir_success_count > dir_fail_count else RED
            perc = round(dir_success_count/(dir_fail_count + dir_success_count) * 100, 2)
            print(f"{BOLD}{GREEN}PASS {dir_success_count}{RESET}, "
                  f"{BOLD}{RED}FAIL {dir_fail_count}{RESET} ({perc_color}{perc}%{RESET}) "
                  f"FROM {BRIGHT_BLUE}{dirpath}{RESET}\n")

    if testing:
        success_rate = round(success_count/test_case_count * 100, 2)
        print(f"{BOLD}Passed {success_count} of {test_case_count} cases: "
              f"{GREEN if success_rate > 50 else RED}{success_rate}%{RESET}")
        if len(failed_cases) > 0:
            fail_str = "\n".join([f for f in failed_cases])
            print(f"Failed Test Cases:\n{fail_str}")


# Use config params and command to construct full command
def construct_cmd(fname: str) -> str:
    base_cmd = cfg["running"]["run_command"]
    return base_cmd.replace("?", fname)


# Executes the running of the program with supplied file
def run_file(fname: str) -> None:
    run_cmd = construct_cmd(fname)

    print(f"{BRIGHT_BLUE}Running: {fname}{RESET}")
    stdout, stderr = execute_command(run_cmd)

    if stdout:
        print(f"\033[43m\033[30mStdOut:{RESET}\n{stdout}")

    elif stderr:
        print(f"StdErr:\n{stderr}")


def find_expected(fname: str) -> str:
    """Find the expected test case result file"""
    expect_name = f"expected_{fname.split(os.sep)[-1]}"
    expect_path = cfg["paths"]["expected_dir"]
    for (dirpath, _, filenames) in os.walk(expect_path):
        if expect_name in filenames:
            return os.path.join(dirpath, expect_name)
    return ""


def test_file(fname: str) -> bool:
    """Start process to test a single file"""
    global test_case_count
    test_case_count += 1

    run_cmd = construct_cmd(fname)

    dbgprint(f"Testing File: {fname}")
    stdout, stderr = execute_command(run_cmd)

    if stdout:
        expected_file = find_expected(fname)
        if not expected_file:
            eprint(f"Expected result file for {fname} not found")
            return False

        with open(expected_file) as f:
            expected_contents = f.read()

        short_path = gen_short_path(fname)
        if stdout == expected_contents:
            if cfg["testing"].getboolean("show_individual"):
                print(f"CASE {test_case_count} "
                      f"{BRIGHT_BLUE}{short_path}{RESET} {GREEN}PASSED{RESET}")
            dbgprint(stdout)
            return True
        else:
            if cfg["testing"].getboolean("show_individual"):
                print(f"CASE {test_case_count} "
                      f"{BRIGHT_BLUE}{short_path}{RESET} {RED}FAILED{RESET}")
            return False

    elif stderr:
        eprint(stderr)
        return False

    dbgprint("Stderr and stdout blank!")
    return False


def gen_short_path(full_path: str) -> str:
    """Generate shortened version of a full path, for display purposes"""
    # for whatever insane reason if the full path is too short
    if full_path.count(os.sep) >= 2:
        return f"...{os.sep}{os.sep.join(full_path.split(os.sep)[-2:])}"
    else:
        return full_path


def execute_command(cmd: str) -> tuple[str, str]:
    """Execute Shell Command"""
    try:
        process = subprocess.Popen(
            cmd,
            shell=True,
            preexec_fn=os.setsid,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True # decode output as text
        )

        stdout, stderr = process.communicate()

        process.wait()

        if process.returncode != 0:
            return "", f"Error occurred, return code {process.returncode}: {stderr}"

        return stdout, stderr

    except KeyboardInterrupt:
        # handle Ctrl-C gracefully
        print("Terminating Subprocess")
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        sys.exit(0)

    finally:
        if process.poll() is None:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)


def eprint(*args, **kwargs) -> None:
    """Print error for a case, no termination"""
    print(f"{BOLD}{RED}[ERROR]{RESET}", *args, file=sys.stderr, **kwargs)


def dbgprint(*args, **kwargs) -> None:
    if debug:
        print(f"{BOLD}{MAGENTA}[DEBUG]{RESET}", *args, **kwargs)


def main() -> None:
    global cfg, debug, testing
    cfg.read("config.ini")
    debug = cfg["running"].getboolean("debug")
    testing = cfg["testing"].getboolean("testing")
    run()


if __name__ == '__main__':
    main()
