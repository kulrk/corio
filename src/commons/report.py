# -*- coding: utf-8 -*-
# !/usr/bin/python
#
# Copyright (c) 2022 Seagate Technology LLC and/or its Affiliates
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
#
# For any questions about this software or licensing,
# please email opensource@seagate.com or cortx-questions@seagate.com.
#

"""Report module to generate the execution details."""

import logging
from datetime import datetime
from typing import Union

import time
import yaml

import pandas as pd

from src.commons.constants import ROOT, CORIO_MASTER_CONFIG
from src.commons.commands import GREP_CMD_ERROR, GREP_CMD_ITERATION
from src.commons.utils.corio_utils import convert_size, get_report_file_path
from src.commons.utils.corio_utils import get_test_file_path
from src.commons.utils.corio_utils import run_local_cmd

LOGGER = logging.getLogger(ROOT)


def log_status(parsed_input: dict, corio_start_time: datetime, **kwargs):
    """
    Log execution status into log file.

    :param parsed_input: Dict for all the input yaml files.
    :param corio_start_time: Start time for main process.
    # :param test_failed: Reason for failure is any.
    # :param terminated_tests: terminated tests from workload.
    """
    test_failed = kwargs.get("test_failed")
    status_fpath = get_report_file_path(corio_start_time)
    LOGGER.info("Logging current status to %s", status_fpath)
    with open(status_fpath, 'w', encoding="utf-8") as status_file:
        status_file.write(f"\nLogging Status at {datetime.now()}")
        if test_failed == 'KeyboardInterrupt':
            status_file.write("\nTest Execution stopped due to Keyboard interrupt")
        elif test_failed is None:
            status_file.write('\nTest Execution still in progress')
        else:
            status_file.write(f'\nTest Execution terminated due to error in {test_failed}')
        status_file.write(f'\nTotal Execution Duration : {datetime.now() - corio_start_time}')
        status_file.write("\nTestWise Execution Details:")
        for key, value in parsed_input.items():
            dataframe = pd.DataFrame()
            pd.set_option('display.colheader_justify', 'center')
            for key1, value1 in value.items():
                input_dict = {"TEST_NO": key1,
                              "TEST_ID": value1['TEST_ID'],
                              "SESSIONS": int(value1['sessions'])}
                convert_object_size(input_dict, value1)
                update_tests_status(input_dict, corio_start_time, value1, **kwargs)
                dataframe = dataframe.append(input_dict, ignore_index=True)
            # Convert sessions into integer.
            dataframe = dataframe.astype({"SESSIONS": 'int'})
            status_file.write(f"\n\nTEST YAML FILE : {key}\n")
            dataframe.to_string(status_file)


def convert_object_size(input_dict: dict, value: Union[dict, list]) -> None:
    """
    Convert object size for reporting.

    :param input_dict: Dict for all the input yaml files.
    :param value: Dict/List/int for object size.
    """
    if isinstance(value['object_size'], list):
        input_dict["OBJECT_SIZE"] = [convert_size(x) for x in value['object_size']]
    elif isinstance(value['object_size'], dict):
        if 'start' in value['object_size']:
            input_dict.update({"OBJECT_SIZE_START": convert_size(value['object_size']['start']),
                               "OBJECT_SIZE_END": convert_size(value['object_size']['end'])})
        else:
            for key, _value in value['object_size'].items():
                input_dict.update({convert_size(key): _value })
    else:
        input_dict["OBJECT_SIZE"] = convert_size(value['object_size'])

# pylint: disable-msg=too-many-locals
def update_tests_status(input_dict: dict, corio_start_time: datetime, value: dict, **kwargs):
    """
    Update tests status in report.

    :param input_dict: Dict for all the input yaml files.
    :param corio_start_time: start time of workload execution.
    :param value: test details from workload execution.
    """
    # List of the test cases from terminated tp.
    terminated_tests = kwargs.get("terminated_tests", [])
    sequential_run = kwargs.get("sequential_run")
    # Reason of the test execution failure.
    test_failed = kwargs.get("test_failed", '')
    test_start_time = corio_start_time + value['start_time']
    start_iterations_count = 0
    completed_iterations_count = 0
    fpath = get_test_file_path(corio_start_time, input_dict['TEST_ID'])
    yaml_file = CORIO_MASTER_CONFIG
    print(CORIO_MASTER_CONFIG)
    LOGGER.debug("YAML file selected for parse: %s", yaml_file)
    yaml_dict = {}
    with open(yaml_file, "r", encoding="utf-8") as obj:
        data = yaml.safe_load(obj)
        yaml_dict.update(data)
    LOGGER.debug("YAML file data: %s", yaml_dict)
    if datetime.now() > test_start_time:
        input_dict["START_TIME"] = f"Started at {test_start_time.strftime('%Y-%m-%d %H:%M:%S')}"
        input_dict["RESULT_UPDATE"] = "In Progress"
        if yaml_dict['s3api']['wait_on_operation'] is True:
            with open(fpath, 'r') as test_log_file:
                lines = test_log_file.readlines()
                for line in lines:
                    if 'iteration' in line.lower():
                        line = line.split()
                        if 'started' in line:
                            start_iterations_count+=1
                        if 'completed' in line:
                            completed_iterations_count+=1
                LOGGER.info(start_iterations_count)
                LOGGER.info(completed_iterations_count)
            test_log_file.close()
            if datetime.now() > (test_start_time + value['min_runtime']) and \
                            start_iterations_count == completed_iterations_count:
                pass_time = (test_start_time + value['min_runtime']).strftime('%Y-%m-%d %H:%M:%S')
                input_dict["RESULT_UPDATE"] = f"Passed at {pass_time}"
                total_execution_time = value['min_runtime'] if sequential_run else datetime.now(
                ) - test_start_time
            else:
                LOGGER.info("Open and parse log file to check if condition recursively")
                flag = True
                while flag:
                    resp = run_local_cmd(GREP_CMD_ITERATION.format(start_iterations_count, fpath))
                    result = run_local_cmd(GREP_CMD_ERROR.format(fpath))
                    if resp:
                        flag = False
                        pass_time = (test_start_time + datetime.now()).strftime('%Y-%m-%d %H:%M:%S')
                        input_dict["RESULT_UPDATE"] = f"Passed at {pass_time}"
                        total_execution_time = value['min_runtime'] if sequential_run \
                                                 else datetime.now() - test_start_time
                    elif result:
                        flag = False
                    else:
                        LOGGER.info("Wait for iteration to complete and check again")
                        time.sleep(30)
        else:
            if datetime.now() > (test_start_time + value['min_runtime']):
                pass_time = (test_start_time + value['min_runtime']).strftime('%Y-%m-%d %H:%M:%S')
                input_dict["RESULT_UPDATE"] = f"Passed at {pass_time}"
                total_execution_time = value['min_runtime'] if sequential_run else datetime.now(
                ) - test_start_time
            else:
                # Report In Progress, Fail, Aborted and update status.
                if input_dict["TEST_ID"] in terminated_tests:
                    LOGGER.error("Test execution terminated due to error in %s.", input_dict["TEST_ID"])
                    input_dict["RESULT_UPDATE"] = "Fail"
                elif test_failed:
                    input_dict["RESULT_UPDATE"] = "Aborted"
                else:
                    input_dict["RESULT_UPDATE"] = "In Progress"
                total_execution_time = datetime.now() - test_start_time
            input_dict["TOTAL_TEST_EXECUTION"] = total_execution_time
    else:
        input_dict["START_TIME"] = f"Scheduled at {test_start_time.strftime('%Y-%m-%d %H:%M:%S')}"
        input_dict["RESULT_UPDATE"] = "Not Triggered"
        input_dict["TOTAL_TEST_EXECUTION"] = "NA"
