import copy
import json

import yaml

from default.model_factory import filter_model_object_factory
from default.utils import get_system_property
# from default.model_factory import filter_model_object_factory, get_model_object_factory
# from default.utils import get_system_property
from .models import *
from datetime import datetime, timedelta
import csv
from io import StringIO
import base64
import math
from collections import namedtuple
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from django.core.cache import cache
from api.celery import app
from .exceptions import InvalidApplicationException, InvalidMonthException, ValueOutOfRangeException
from django.conf import settings
import logging
LOGGER = logging.getLogger('django')


# {
#     "name":"Dora Mecs",
#     "evaluation_strategy":10000,
#     "metric_monitoring_list":[
#       {
#         "name":"deployment_frequency",
#         "metric_evaluation_strategy":10000,
# "source_key":"deployment_frequency",
#    "source_url":"https://example.com/"
#
#         "metric_parameters":[{
#           "data_source_type":10000,
#           "source_path_index":8,
#           "data_type":10000,
#           "name":"deployment_frequency",
#           "metal_rating_evaluation":[
#             {"metal_rating":10000,
#               "operator": 10000,
#               "value":"4"
#             }
#           ]
#         }]
#       }
#       ]
#   }

# # {
#     "application":"rr",
#     "environment":"dev",
#     "service":"ser",
#     "organization":"bp",
#     "source_key":"jj",//tools identifier
#     "report_data":{"deployment_frequency":1,"MTTR":2,"Lead time to change":3,"change_failure_rate":2}
#     "report_file_path"  :null
# # }

def set_metal_rating_hierarchy_to_cache():
    metal_rating_list=list(MetalRating.objects.all().values_list('name',flat=True))
    cache.set("PICK_HIGHEST",metal_rating_list)
    cache.set("PICK_LOWEST",metal_rating_list[::-1])

def set_metal_rating_model_to_cache():
    metal_rating_list=MetalRating.objects.all()
    cache.set("METAL_RATING_LIST",metal_rating_list)

def set_metric_group_and_metric_index_to_cache(metric_group_serialized_data):
    metric_group_json=cache.get("metric_group_index_mapping",{})
    metric_group_json[metric_group_serialized_data['name']]={'index':[],"strategy":metric_group_serialized_data['evaluation_strategy']['name']}
    for metric in metric_group_serialized_data['metric_monitoring_list']:
        metric_group_json[metric_group_serialized_data['name']]['index'].append(metric['name'])
        cache.set(metric['name'],metric)
    cache.set("metric_group_index_mapping",metric_group_json)

def set_all_metric_group_and_metric_index_to_cache(all_metric_group_serialized_data):
    metric_group_json={}
    for metric_group in all_metric_group_serialized_data:
        metric_group_json[metric_group['name']]={"index":[],"strategy":metric_group['evaluation_strategy']['name']}
        for metric in metric_group['metric_monitoring_list']:
            metric_group_json[metric_group['name']]['index'].append(metric['name'])
            cache.set(metric['name'],metric)
    cache.set("metric_group_index_mapping",metric_group_json)



def evaluate_metric_value_against_metal_value(metric_value,metal_operator,metal_value=None,lower_limit=None,upper_limit=None):
    if metal_operator['name'] == "LESS_THAN":
        result=eval(f"{metric_value} < {metal_value}")
    elif metal_operator['name'] == "LESS_THAN_EQUAL_TO":
        result=eval(f"{metric_value} <= {metal_value}")
    elif metal_operator['name'] == "GREATER_THAN":
        result=eval(f"{metric_value} > {metal_value}")
    elif metal_operator['name'] == "GREATER_THAN_EQUAL_TO":
        result=eval(f"{metric_value} >= {metal_value}")
    elif metal_operator['name'] == "BETWEEN":
        result=eval(f"{metric_value} > {lower_limit} and {metric_value} <= {upper_limit}")
    elif metal_operator['name'] == "EQUAL_TO":
        result=eval(f"{metric_value} = {metal_value}")
    elif metal_operator['name'] == "NOT_EQUAL_TO":
        result=eval(f"{metric_value} != {metal_value}")
    return result

def scale_day_metal_value(day,period,period_value,metal_value=None,metal_lower_limit=None,metal_upper_limit=None):
    value=lower_limit=upper_limit=None

    if metal_value is not None:
        value=float(metal_value) * period_value
    if metal_lower_limit is not None:
        lower_limit=float(metal_lower_limit) * period_value
    if metal_upper_limit is not None:
        upper_limit=float(metal_upper_limit) * period_value

    return value,lower_limit,upper_limit


def evaluate_metal_rating_per_period(metal_level_evaluation_metrix_list, period, period_value):
    metal_level_evaluation_metrix=[]
    for obj in metal_level_evaluation_metrix_list:
        matrix=copy.deepcopy(obj)
        value=lower_limit=upper_limit=None
        if obj['period']['name'] == "DAY":
            configured_period_value=1
        elif obj['period']['name'] == "WEEK":
            configured_period_value=get_system_property("DAY_IN_A_WEEK")
        elif obj['period']['name'] == "MONTH":
            configured_period_value=get_system_property("DAY_IN_A_MONTH")
        elif obj['period']['name'] == "YEAR":
            configured_period_value=get_system_property("DAY_IN_A_YEAR")
        if obj["value"]:
            value = float(obj["value"]) / configured_period_value
        if obj["lower_limit"]:
            lower_limit = float(obj["lower_limit"]) / configured_period_value
        if obj["upper_limit"]:
            upper_limit = float(obj["upper_limit"]) / configured_period_value
        value, lower_limit, upper_limit = scale_day_metal_value("DAY", period, period_value, value, lower_limit, upper_limit)
        matrix['value']=value
        matrix['lower_limit']=lower_limit
        matrix['upper_limit']=upper_limit
        metal_level_evaluation_metrix.append(matrix)
    return metal_level_evaluation_metrix


def evaluate_metal_value(metric_key_value,metal_level_evaluation_metrix_list):
    for metal_level_evaluation_metrix in metal_level_evaluation_metrix_list:

        operator = metal_level_evaluation_metrix["operator"]
        if evaluate_metric_value_against_metal_value(metric_key_value,operator,metal_level_evaluation_metrix["value"],metal_level_evaluation_metrix["lower_limit"],metal_level_evaluation_metrix["upper_limit"]):
            
            return metal_level_evaluation_metrix['metal_rating']['name'], metric_key_value
        else:
            continue
    raise ValueOutOfRangeException(f"{metric_key_value} doesn't lie in the range")

def evaluate_period_metal_value(metric_key_value,metal_level_evaluation_metrix_list,period,period_value):

    scaled_metal_level_evaluation_metrices=evaluate_metal_rating_per_period(metal_level_evaluation_metrix_list,period,period_value)

    for metal_level_evaluation_metrix in scaled_metal_level_evaluation_metrices:
        operator = metal_level_evaluation_metrix["operator"]
        if evaluate_metric_value_against_metal_value(metric_key_value,operator,metal_level_evaluation_metrix["value"],metal_level_evaluation_metrix["lower_limit"],metal_level_evaluation_metrix["upper_limit"]):

            return (
                metal_level_evaluation_metrix['metal_rating']['name'],
                metric_key_value,
                scaled_metal_level_evaluation_metrices,
            )
        else:
            continue
    raise ValueOutOfRangeException(f"{metric_key_value} doesn't lie in the range")

def calculate_current_week(current_datetime):

    # Calculate ISO week number
    _, week_number, _ = current_datetime.isocalendar()

    return week_number

def get_value(key,metric_data):
    return metric_data[key]

def decode_base64_encoded_file_content(content):
    # Decode the base64-encoded CSV content
    decoded_bytes = base64.b64decode(content)
    # Convert bytes to a string (assuming CSV is UTF-8 encoded)
    decoded_csv_string = decoded_bytes.decode('utf-8')
    return decoded_csv_string

def read_csv_content(csv_content):
    # Create a StringIread_csv_contentO object to simulate a file-like object from the CSV content
    csv_content=decode_base64_encoded_file_content(csv_content)
    csv_file = StringIO(csv_content)
    # Create a CSV reader from the StringIO object
    csv_reader = csv.reader(csv_file)
    # Read the first row from the CSV data is header
    header = next(csv_reader, None)
    return csv_reader


def read_csv_file(csv_file_path):
    csvfile=open(csv_file_path, 'r', newline='')
    csv_reader = csv.reader(csvfile)
    header = next(csv_reader, None)
    return csv_reader


def get_value_from_csv_row(first_row, column_index):
    if first_row:
        return first_row[column_index]
    else:
        return None, None
# TODO get_metric_level_metal_value
# debug log


def get_metric_level_metal_value(evaluation_strategy, parameter_dict):
    # TODO O(n) optimization
    # hierarchy from cache
    metal_hierarchy = cache.get(evaluation_strategy, None)
    if not metal_hierarchy:
        set_metal_rating_hierarchy_to_cache()
        metal_hierarchy = cache.get(evaluation_strategy)

    if evaluation_strategy in ["PICK_HIGHEST", "PICK_LOWEST"]:
        parameter_metal_level_mapping = {}
        for parameter in parameter_dict:
            parameter_metal_level_mapping[parameter_dict[parameter]
                                          ['level']] = parameter
        for metal in metal_hierarchy:
            if metal in parameter_metal_level_mapping:
                parameter = parameter_metal_level_mapping[metal]
                # TODO return level only
                return parameter_dict[parameter]["level"]

    elif evaluation_strategy == "AVERAGE":
        metal_level = 0
        type = ''
        for parameter in parameter_dict:
            type = parameter_dict[parameter]['type']

            metal_level += get_metal_score(parameter_dict[parameter]['level'])

        average_metal_level = metal_level / len(parameter_dict)

        return get_metal_name(average_metal_level)


def get_metal_score(metal):
    # TODO need to validate with better approach
    # check why integer is coming
    try:
        metal_rating = MetalRating.objects.get(name=metal)
    except MetalRating.DoesNotExist as err:
        return 0
    else:
        return metal_rating.upper_limit


def get_metal_name(score):
    metal_rating_list = cache.get("METAL_RATING_LIST", None)
    if not metal_rating_list:
        set_metal_rating_model_to_cache()
        metal_rating_list = cache.get("METAL_RATING_LIST", None)

    for metal_rating in metal_rating_list:
        if score >= metal_rating.lower_limit and score <= metal_rating.upper_limit:
            return metal_rating.name


def weeks_in_month(year, month):
    # Find the first day of the month
    first_day = datetime(year, month, 1)
    # Calculate the last day of the month
    next_month = first_day.replace(day=28) + timedelta(days=4)
    last_day = next_month - timedelta(days=next_month.day)
    # Calculate the number of ISO weeks
    num_weeks = (last_day - first_day).days // 7 + 1
    return num_weeks


def handle_sum_aggregation_strategy(instance, parameter_list):
    default_value = None
    type = None
    period = None

    if isinstance(instance, MetricDataDateWise):
        period = "DAY"
        period_value = 1
    elif isinstance(instance, MetricDataWeekWise):
        period = "WEEK"
        period_value = get_system_property("DAY_IN_A_WEEK")
    elif isinstance(instance, MetricDataMonthWise):
        period = "MONTH"
        period_value = get_system_property("DAY_IN_A_MONTH")
    elif isinstance(instance, MetricDataYearWise):
        period = "YEAR"
        period_value = get_system_property("DAY_IN_A_YEAR")

    metric_parameter_data = instance.metric_parameters_data
    default_metal_level_evaluation_matrix={}
    for parameter in parameter_list:
        parameter_value = 0

        if metric_parameter_data:
            metric_parameter_data[parameter]["value"] = metric_parameter_data[parameter]["value"] + \
                parameter_list[parameter]["value"]
        else:
            metric_parameter_data[parameter] = parameter_list[parameter]

        metal_rating_evaluation_list = parameter_list[parameter]["metal_rating_evaluation"]

        metal_level, metal_value, metal_level_evaluation_metrix_list = evaluate_period_metal_value(
            metric_parameter_data[parameter]["value"], metal_rating_evaluation_list, period, period_value)
        if (not instance.metric_parameters_data or parameter not in instance.metric_parameters_data):
            instance.metric_parameters_data[parameter] = {}

        instance.metric_parameters_data[parameter]["value"] = metal_value
        instance.metric_parameters_data[parameter]["level"] = metal_level
        instance.metric_parameters_data[parameter][
            "metal_rating_evaluation"
        ] = metal_level_evaluation_metrix_list
        # check and set default value for metric
        if parameter_list[parameter]["default_display_parameter"]:
            
            default_value = metal_value
            type = parameter_list[parameter]["type"]
            metric_index=instance.metric_group_index.name
            default_metal_level_evaluation_matrix=get_rating_evaluation_in_human(metric_index,metal_level_evaluation_metrix_list,type,period)
    # get paramter_json on the basis of strategy and set metal level of metric index
    metric_level = get_metric_level_metal_value(
        instance.metric_group_index.metric_evaluation_strategy.name, instance.metric_parameters_data)

    instance.metric_data['value'] = default_value
    instance.metric_data["level"] = metric_level
    instance.metric_data['type'] = type
    # instance.metric_data['period']=period
    instance.metric_data['rating']=default_metal_level_evaluation_matrix
    instance.save()
    return instance


def handle_average_aggregation_strategy(instance, parameter_list):
    default_value = None
    type = None
    metric_parameter_data = instance.metric_parameters_data
    default_metal_level_evaluation_matrix={}
    for parameter in parameter_list:
        if metric_parameter_data:
            if parameter in metric_parameter_data:
                metric_parameter_data[parameter]["value"] = (metric_parameter_data[parameter]["value"]
                                                             * metric_parameter_data[parameter]["count"]
                                                             + parameter_list[parameter]["value"]) / (metric_parameter_data[parameter]["count"] + 1)
                metric_parameter_data[parameter]["count"] += 1
            else:
                metric_parameter_data[parameter] = parameter_list[parameter]
                metric_parameter_data[parameter]["count"] = 1
        else:
            metric_parameter_data[parameter] = parameter_list[parameter]
            metric_parameter_data[parameter]["count"] = 1
        metal_rating_evaluation_list = parameter_list[parameter]["metal_rating_evaluation"]
        metal_level, metal_value = evaluate_metal_value(
            metric_parameter_data[parameter]["value"], metal_rating_evaluation_list)

        if (not instance.metric_parameters_data or parameter not in instance.metric_parameters_data):
            instance.metric_parameters_data[parameter] = {}

        instance.metric_parameters_data[parameter]["value"] = metal_value
        instance.metric_parameters_data[parameter]["level"] = metal_level
        instance.metric_parameters_data[parameter][
            "metal_rating_evaluation"
        ] = metal_rating_evaluation_list

        # check and set default value for metric
        if parameter_list[parameter]["default_display_parameter"]:
            default_value = metal_value
            type = parameter_list[parameter]["type"]
            metric_index=instance.metric_group_index.name
            default_metal_level_evaluation_matrix=get_rating_evaluation_in_human(metric_index,metal_rating_evaluation_list,type)
    # get paramter_json on the basis of strategy and set metal level of metric index
    metric_level = get_metric_level_metal_value(
        instance.metric_group_index.metric_evaluation_strategy.name, instance.metric_parameters_data)
    instance.metric_data['value'] = default_value
    instance.metric_data["level"] = metric_level
    instance.metric_data['type'] = type
    instance.metric_data['rating']=default_metal_level_evaluation_matrix
    instance.save()
    return instance

# TODO P2 ensure that the duplicate code is eliminated


def load_initial_data(service, application, environment, organization, metric_index_instance):
    current_datetime = datetime.now()
    date_date = current_datetime.date()
    date_time = current_datetime.time()
    date_week = calculate_current_week(current_datetime)
    date_month = current_datetime.strftime("%b").lower()
    date_year = current_datetime.year
    # get or create new entry in tables for application_service, time ,date, month, year
    try:
        application_service_mapping = ApplicationServiceMapping.objects.get(service_name=service, application_name=application,
                                                                            environment=environment, organization=organization)
    except ApplicationServiceMapping.DoesNotExist as er:
        application_service_mapping = ApplicationServiceMapping.objects.create(service_name=service, application_name=application,
                                                                               environment=environment, organization=organization)
    try:
        year_metric_index_data = MetricDataYearWise.objects.get(year=date_year, application_service_mapping=application_service_mapping,
                                                                metric_group_index=metric_index_instance)
    except MetricDataYearWise.DoesNotExist as er:
        # calculate_previous_year_data
        year_metric_index_data = MetricDataYearWise.objects.create(year=date_year, application_service_mapping=application_service_mapping,
                                                                   metric_group_index=metric_index_instance, metric_data={})

    try:
        month_metric_index_data = MetricDataMonthWise.objects.get(month=date_month, year_metric_data=year_metric_index_data,
                                                                  application_service_mapping=application_service_mapping,
                                                                  metric_group_index=metric_index_instance)
    except MetricDataMonthWise.DoesNotExist as er:
        month_metric_index_data = MetricDataMonthWise.objects.create(month=date_month, year_metric_data=year_metric_index_data,
                                                                     application_service_mapping=application_service_mapping,
                                                                     metric_group_index=metric_index_instance, metric_data={})

    try:
        week_metric_index_data = MetricDataWeekWise.objects.get(
            week=date_week, month_metric_data=month_metric_index_data, application_service_mapping=application_service_mapping, metric_group_index=metric_index_instance)
    except MetricDataWeekWise.DoesNotExist as er:
        # last_week_data
        week_metric_index_data = MetricDataWeekWise.objects.create(
            week=date_week, month_metric_data=month_metric_index_data, application_service_mapping=application_service_mapping, metric_group_index=metric_index_instance, metric_data={})

    try:
        day_metric_index_data = MetricDataDateWise.objects.get(
            date=date_date, week_metric_data=week_metric_index_data, application_service_mapping=application_service_mapping, metric_group_index=metric_index_instance)
    except MetricDataDateWise.DoesNotExist as er:
        day_metric_index_data = MetricDataDateWise.objects.create(date=date_date, week_metric_data=week_metric_index_data,
                                                                  application_service_mapping=application_service_mapping, metric_group_index=metric_index_instance, metric_data={})

    try:
        time_metric_index_data = MetricDataDateTimeWise.objects.get(
            time=date_time, date_metric_data=day_metric_index_data, application_service_mapping=application_service_mapping, metric_group_index=metric_index_instance)
    except MetricDataDateTimeWise.DoesNotExist as er:
        time_metric_index_data = MetricDataDateTimeWise.objects.create(
            time=date_time, date_metric_data=day_metric_index_data, application_service_mapping=application_service_mapping, metric_group_index=metric_index_instance, metric_data={})
    return application_service_mapping, time_metric_index_data, day_metric_index_data, week_metric_index_data, month_metric_index_data, year_metric_index_data

# TODO same the complete value:operator:range_json


def generate_response_body(metal_rating_evaluation_list):
    response = ""
    for metal_rating in metal_rating_evaluation_list:
        response = response + f" {metal_rating['operator']['name']}"
    return response


def evaluate_metal_rating_for_a_parameter(parameter, parameter_dict, metric_key_value):
    parameter_name = parameter['name']
    response_body = {}
    metal_rating_evaluation_list = parameter["metal_rating_evaluation"]
    try:
        metal_level, metal_value = evaluate_metal_value(
            metric_key_value, metal_rating_evaluation_list)
    except ValueOutOfRangeException as e:
        response = generate_response_body(metal_rating_evaluation_list)
        raise ValueOutOfRangeException(str(e), response_body=response)
    except Exception as e:
        raise Exception(e)

    parameter_dict[parameter_name] = {
        "default_display_parameter": parameter['default_display_parameter'],
        "level": metal_level,
        "value": metal_value,
        "type": parameter['data_type']['name'],
        "metal_rating_evaluation": metal_rating_evaluation_list,
    }
    return parameter_dict


def prepare_metric_index_data_as_per_aggregation_strategy(instance, metric_index_instance_serialized_data, parameter_list):
    if metric_index_instance_serialized_data['metric_aggregation_strategy']['name'] == "PER_PERIOD":
        instance = handle_sum_aggregation_strategy(instance, parameter_list)

    elif metric_index_instance_serialized_data['metric_aggregation_strategy']['name'] == "PER_SCAN":
        instance = handle_average_aggregation_strategy(
            instance, parameter_list)

    instance.save()
    return instance


def update_day_metric_index_data(day_metric_index_data, metric_index_instance_serialized_data, parameter_list):

    day_metric_index_data = prepare_metric_index_data_as_per_aggregation_strategy(
        day_metric_index_data, metric_index_instance_serialized_data, parameter_list)
    return day_metric_index_data


def update_week_metric_index_data(week_metric_index_data, metric_index_instance_serialized_data, parameter_list):

    week_metric_index_data = prepare_metric_index_data_as_per_aggregation_strategy(
        week_metric_index_data, metric_index_instance_serialized_data, parameter_list)
    return week_metric_index_data


def update_month_metric_index_data(month_metric_index_data, metric_index_instance_serialized_data, parameter_list):

    month_metric_index_data = prepare_metric_index_data_as_per_aggregation_strategy(
        month_metric_index_data, metric_index_instance_serialized_data, parameter_list)

    return month_metric_index_data


def update_year_metric_index_data(year_metric_index_data, metric_index_instance_serialized_data, parameter_list):

    year_metric_index_data = prepare_metric_index_data_as_per_aggregation_strategy(
        year_metric_index_data, metric_index_instance_serialized_data, parameter_list)

    return year_metric_index_data


def convert_value_to_specific_data_type(parameter, metric_key_value):
    if parameter['data_type']['name'] in ['INT', "TIME", "PERCENTAGE"]:
        metric_key_value = float(metric_key_value)
    return metric_key_value


def prepare_parameter_metal_rating_for_csv_data_source(parameter_list, first_row):
    parameter_dict = {}
    for parameter in parameter_list:
        # reading column index
        source_path_index = int(parameter['source_path_index'])
        try:
            metric_key_value = get_value_from_csv_row(
                first_row, source_path_index)
            metric_key_value = convert_value_to_specific_data_type(
                parameter=parameter, metric_key_value=metric_key_value)
        except IndexError as e:
            return f"column with index {source_path_index} doesn't exist"
        # setting default value of metric index
        if parameter['default_display_parameter']:
            metric_index_value = metric_key_value
            metric_index_type = parameter['data_type']['name']
        # evaluate metal level on the basis of metal rating evaluation matrix
        try:
            parameter_dict = evaluate_metal_rating_for_a_parameter(
                parameter, parameter_dict, metric_key_value)
        except ValueOutOfRangeException as e:
            response_body = f"{metric_key_value} is not {e.response_body}"
            raise ValueOutOfRangeException(str(e), response_body)
        except Exception as e:
            raise Exception(e)
    return metric_index_type, metric_index_value, parameter_dict


def prepare_parameter_metal_rating_for_json_data_source(parameter_list, metric_index_data):
    parameter_dict = {}
    for parameter in parameter_list:
        source_path_index = parameter['source_path_index']  # rr.tt.ss
        source_path_keys = source_path_index.split(".")

        metric_index_json = copy.deepcopy(metric_index_data)
        try:
            for key in source_path_keys:
                metric_key_value = get_value(key, metric_index_json)
                metric_index_json = metric_key_value
            metric_key_value = convert_value_to_specific_data_type(
                parameter=parameter, metric_key_value=metric_key_value)
        except Exception as error:
            raise Exception(str(error))
        # setting default value of metric index
        if parameter['default_display_parameter']:
            metric_index_value = metric_key_value
            metric_index_type = parameter['data_type']['name']
        # evaluate metal level on the basis of metal rating evaluation matrix
        try:
            parameter_dict = evaluate_metal_rating_for_a_parameter(
                parameter, parameter_dict, metric_key_value)
        except ValueOutOfRangeException as e:
            response_body = f"{metric_key_value} doesn't {e.response_body}"
            raise ValueOutOfRangeException(str(e), response_body)
        except Exception as e:
            raise Exception(e)
    return metric_index_type, metric_index_value, parameter_dict

# This method is called whenever a metric data is pushed for a service


def analyse_metric_and_save_to_table(metric):
    # JSON
    # metric = {
    #     "application": "rr1",
    #     "environment": "dev1",
    #     "service": "srv2",
    #     "organization": "bp",
    #     "source_key": "dora",
    #     "report_data": {
    #         "deployment_frequency": 2,
    #         "MTTR": 4,
    #         "lead_time_to_change": 5,
    #         "change_failure_rate": 4,
    #     },
    #     "report_file_path": None,
    # }
    # CSV
    # metric={
    # "application":"rr",
    # "environment":"dev",
    # "service":"srv",
    # "organization":"bp",
    # "source_key":"gitleak",
    # "report_data":"cnIKMQ==",
    # "report_file_path"  :None
    # }
    application = metric.get("application")
    environment = metric.get("environment")
    service = metric.get("service")
    organization = metric.get("organization")
    metric_index_data = metric.get("report_data")
    metric_file_path = metric.get("report_file_path")
    source_key = metric.get("source_key")
    month_wise_metric_data = {}
    
    application_service_mapping=None
    # This data is placed in cache during configuration
    # metric_group_index_mapping ={
    #     Dora_Metrics:{index:["Deployment Frequency","Lead Time to Change"], strategy:"Pick Highest"},
    #     Code_Quality:{index:["Coverty", "Black Duck"],strategy:"Pick Lowest"}
    # }
    metric_group_index_mapping = cache.get("metric_group_index_mapping", {})
    # application_service_index_mapping={
    #     org.application.service:["Deployment Frequency", "Coverty"]
    # }
    application_service_index_mapping = cache.get("application_service_index_mapping", {
                                                  f"{organization}.{application}.{service}": []})
    service_level_metric_group_list = {}
    application_index_mapping = {f"{organization}.{application}": []}
    # get all metric corresponding to the source key
    metric_index_instance_list = filter_model_object_factory(
        "MetricGroupIndex", source_key=source_key)
    metric_index_serialized_data = {}
    for metric_index_instance in metric_index_instance_list:
        metric_index_instance_serialized_data = cache.get(
            metric_index_instance.name)
        application_service_index_mapping[f"{organization}.{application}.{service}"].append(
            metric_index_instance.name)
        application_index_mapping[f"{organization}.{application}"].append(
            metric_index_instance.name)
        metric_index_serialized_data[metric_index_instance.name] = metric_index_instance_serialized_data

        prepare_service_level_metric_group_metric_index_mapping(
            metric_group_index_mapping, service_level_metric_group_list, metric_index_instance)

        (
            application_service_mapping, 
            time_metric_index_data, 
            day_metric_index_data, 
            week_metric_index_data, 
            month_metric_index_data, 
            year_metric_index_data) = load_initial_data(service, application, environment, organization, metric_index_instance)

        parameter_dict = {}
        metric_data = {}
        metric_evaluation_strategy = metric_index_instance_serialized_data[
            'metric_evaluation_strategy']['name']
        parameter_list = metric_index_instance_serialized_data['metric_parameters']
        # handle parameter value
        # one time read file TODO
        metric_index_value = None
        metric_index_type = None
        # read file content or report data
        # TODO make method analyse_input_data
        if metric_index_instance.data_source_type.name == "CSV":
            if metric_file_path:
                csv_file = read_csv_file(metric_file_path)
            else:
                csv_file = read_csv_content(metric_index_data)
            first_row = next(csv_file, None)
            try:
                metric_index_type, metric_index_value, parameter_dict = prepare_parameter_metal_rating_for_csv_data_source(
                    parameter_list, first_row)
            except ValueOutOfRangeException as e:
                return False, e.response_body
            except Exception as e:
                return False, str(e)

        elif metric_index_instance.data_source_type.name in ["JSON", "YAML"]:
            if metric_index_instance.data_source_type.name == 'JSON':
                # reading json from file
                if metric_file_path:
                    file_discriptor = open(metric_file_path, 'r')
                    metric_index_data = json.load(file_discriptor)
            else:
                # reading yaml from file
                if metric_file_path:
                    yaml_content = open(metric_file_path, 'r').read()
                    metric_index_data = yaml.load_all(
                        yaml_content, Loader=yaml.SafeLoader)
                    # for one yaml only
                    for yaml_content in metric_index_data:
                        metric_index_data = yaml_content

            try:
                metric_index_type, metric_index_value, parameter_dict = prepare_parameter_metal_rating_for_json_data_source(
                    parameter_list, metric_index_data)
            except ValueOutOfRangeException as e:
                return False, e.response_body
            except Exception as e:
                return False, str(e)

        metric_data["level"] = get_metric_level_metal_value(
            metric_evaluation_strategy, parameter_dict
        )
        metric_data['value'] = metric_index_value
        metric_data['type'] = metric_index_type
        # calculate and save data in time,date,week,month,year with metal score
        time_metric_index_data.metric_data = metric_data
        time_metric_index_data.metric_parameters_data = parameter_dict
        time_metric_index_data.save()
        parameter_dict_final=copy.deepcopy(parameter_dict)
        # update day,week,month and year data
        day_metric_index_data = update_day_metric_index_data(
            day_metric_index_data, metric_index_instance_serialized_data, parameter_dict)
        parameter_dict=parameter_dict_final
        week_metric_index_data = update_week_metric_index_data(
            week_metric_index_data, metric_index_instance_serialized_data, parameter_dict)
        parameter_dict=parameter_dict_final
        month_metric_index_data = update_month_metric_index_data(
            month_metric_index_data, metric_index_instance_serialized_data, parameter_dict)
        parameter_dict=parameter_dict_final
        set_metric_index_month_data(
            month_wise_metric_data, metric_index_instance, month_metric_index_data)

        year_metric_index_data = update_year_metric_index_data(
            year_metric_index_data, metric_index_instance_serialized_data, parameter_dict)

        # send task sync
    set_month_data_to_service_cache(
        application_service_mapping, month_wise_metric_data)
    
    kwargs = {
        "app_name": application,
        "org": organization,
        "service": service,
        "metric_group_metric_index_mapping": service_level_metric_group_list,
        "application_service_index_mapping": application_service_index_mapping,
        "metric_index_serialized_data": metric_index_serialized_data,
        "application_index_mapping": application_index_mapping,
    }
    task = app.send_task("metric_api.process_metric_data", kwargs=kwargs)
    return True, "data is push successfully"


def prepare_service_level_metric_group_metric_index_mapping(metric_group_index_mapping, service_level_metric_group_list, metric_index_instance):
    if metric_index_instance.metric_group.name not in service_level_metric_group_list:
        service_level_metric_group_list[metric_index_instance.metric_group.name] = metric_group_index_mapping[metric_index_instance.metric_group.name]

        service_level_metric_group_list[metric_index_instance.metric_group.name]['index'] = [
            metric_index_instance.name]
    else:
        if metric_index_instance.name not in service_level_metric_group_list[metric_index_instance.metric_group.name]['index']:
            service_level_metric_group_list[metric_index_instance.metric_group.name]['index'].append(
                metric_index_instance.name)


def set_metric_index_month_data(month_wise_metric_data, metric_index_instance, month_metric_index_data):
    if metric_index_instance.name not in month_wise_metric_data:
        month_wise_metric_data[metric_index_instance.name] = {}
    month_wise_metric_data[metric_index_instance.name][f"{month_metric_index_data.month} {month_metric_index_data.year_metric_data.year}"] = {
        "metric_data": {}, "metric_parameter_data": {}}
    month_wise_metric_data[metric_index_instance.name][f"{month_metric_index_data.month} {month_metric_index_data.year_metric_data.year}"][
        "metric_data"] = month_metric_index_data.metric_data
    month_wise_metric_data[metric_index_instance.name][f"{month_metric_index_data.month} {month_metric_index_data.year_metric_data.year}"][
        "metric_parameter_data"] = month_metric_index_data.metric_parameters_data


def get_next_six_month_names():
    # Get the current date
    current_date = datetime.now()

    # Initialize a list to store month names
    month_names = []
    month_names.append(current_date.strftime('%b %Y').lower())
    # Calculate and append the month names for the next 6 months
    for i in range(1, 6):
        # Calculate the date for the next i-th month using relativedelta
        target_date = current_date - relativedelta(months=i)
        # Get the full month name and append it to the list
        month_names.append(target_date.strftime('%b %Y').lower())

    return month_names


def get_next_six_month_and_year_names():
    # Get the current date
    current_date = datetime.now()

    # Initialize a list to store month names
    month_names = []
    month_names.append(current_date.strftime('%b %Y').lower())
    # Calculate and append the month names for the next 6 months
    for i in range(1, 6):
        # Calculate the date for the next i-th month using relativedelta
        target_date = current_date - relativedelta(months=i)
        # Get the full month name and append it to the list
        month_names.append(target_date.strftime('%b %Y').lower())

    return month_names


def prepare_across_month_handle_sum_aggregation_strategy(org, app_name, service, metric_evaluation_strategy, parameter_list, month_list, application_service_dict, metric_index):
    default_value = None
    type = None
    period = None
    period = "HALF_YEAR"
    period_value = len(month_list) * get_system_property("DAY_IN_A_MONTH")
    metric_parameters_data = {}
    metric_data = {}
    metal_rating_evaluation_list = None
    default_metal_level_evaluation_matrix={}
    for parameter in parameter_list:
        parameter_value = 0
        month_count=0
        parameter_name = parameter['name']
        for month in month_list:
            if month in application_service_dict[f"{org}.{app_name}.{service}"]['metric_index_data'][metric_index]["month_wise_data"]:
                month_count+=1
                parameter_value += application_service_dict[f"{org}.{app_name}.{service}"]['metric_index_data'][
                    metric_index]["month_wise_data"][month]['metric_parameter_data'][parameter_name]['value']

        parameter_value_avg = parameter_value
        metal_rating_evaluation_list = parameter['metal_rating_evaluation']
        metal_level, metal_value, metal_level_evaluation_metrix_list = evaluate_period_metal_value(
            parameter_value_avg, metal_rating_evaluation_list, period, period_value)
        metric_parameters_data[parameter_name] = {}
        metric_parameters_data[parameter_name]['value'] = metal_value
        metric_parameters_data[parameter_name]['level'] = metal_level
        metric_parameters_data[parameter_name]['metal_rating_evaluation'] = metal_level_evaluation_metrix_list
        # check and set default value for metric
        if parameter['default_display_parameter']:
            default_value = metal_value
            type = parameter['data_type']['name']
            default_metal_level_evaluation_matrix=get_rating_evaluation_in_human(metric_index,metal_level_evaluation_metrix_list,type,period)
    # get paramter_json on the basis of strategy and set metal level of metric index
    metric_level = get_metric_level_metal_value(
        metric_evaluation_strategy, metric_parameters_data)
    metric_data['value'] = default_value
    metric_data["level"] = metric_level
    metric_data['type'] = type
    # metric_data['period']=period
    metric_data['rating']= default_metal_level_evaluation_matrix
    return metric_data, metric_parameters_data


def prepare_across_month_handle_average_aggregation_strategy(org, app_name, service, metric_evaluation_strategy, parameter_list, month_list, application_service_dict, metric_index):
    default_value = None
    type = None
    metric_parameters_data = {}
    metric_data = {}
    default_metal_level_evaluation_matrix={}
    for parameter in parameter_list:
        parameter_value = 0
        parameter_name = parameter['name']
        count=0
        for month in month_list:
            if month in application_service_dict[f"{org}.{app_name}.{service}"]['metric_index_data'][metric_index]["month_wise_data"]:
                if application_service_dict[f"{org}.{app_name}.{service}"]['metric_index_data'][
                    metric_index]["month_wise_data"][month]['metric_parameter_data']:
                    count+=1
                    parameter_value += application_service_dict[f"{org}.{app_name}.{service}"]['metric_index_data'][
                        metric_index]["month_wise_data"][month]['metric_parameter_data'][parameter_name]['value']
        try:
            parameter_value_avg = parameter_value/
