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
        return None
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
            parameter_value_avg = parameter_value/count
        except ZeroDivisionError as e:
            parameter_value_avg = parameter_value
        metal_rating_evaluation_list = parameter['metal_rating_evaluation']
        metal_level, metal_value = evaluate_metal_value(
            parameter_value_avg, metal_rating_evaluation_list)
        metric_parameters_data[parameter_name] = {
            'value': metal_value, 'level': metal_level, 'type': parameter['data_type']['name']}
        metric_parameters_data[parameter_name]['metal_rating_evaluation'] = metal_rating_evaluation_list

        # check and set default value for metric
        if parameter['default_display_parameter']:
            default_value = metal_value
            type = parameter['data_type']['name']
            default_metal_level_evaluation_matrix=get_rating_evaluation_in_human(metric_index,metal_rating_evaluation_list,type)
    # get paramter_json on the basis of strategy and set metal level of metric index
    metric_level = get_metric_level_metal_value(
        metric_evaluation_strategy, metric_parameters_data)
    metric_data['value'] = default_value
    metric_data["level"] = metric_level
    metric_data['type'] = type
    metric_data['rating']= default_metal_level_evaluation_matrix
    return metric_data, metric_parameters_data


def evaluate_application_level_metal_rating_per_period(metal_level_evaluation_metrix_list, period, period_value):

    metal_level_evaluation_metrix_named_tuple_list = []
    # generate metal value for day,week,month,year
    # first scale down to day then scale up to year
    for obj in metal_level_evaluation_metrix_list:

        value, lower_limit, upper_limit = scale_day_metal_value(
            "DAY", period, period_value, obj['value'], obj['lower_limit'], obj['upper_limit'])
        metal_level_evaluation_metrix_named_tuple_list.append(
            {'operator': obj['operator'], 'value': value, 'upper_limit': upper_limit, "lower_limit": lower_limit, "metal_rating": obj['metal_rating'],"period":obj['period']})

    return metal_level_evaluation_metrix_named_tuple_list


def evaluate_application_level_period_metal_value(metric_key_value, metal_level_evaluation_metrix_list, period, period_value):
    metal_level_evaluation_metrix_list = evaluate_application_level_metal_rating_per_period(
        metal_level_evaluation_metrix_list, period, period_value)
    for metal_level_evaluation_metrix in metal_level_evaluation_metrix_list:
        operator = metal_level_evaluation_metrix['operator']
        if evaluate_metric_value_against_metal_value(metric_key_value, operator, metal_level_evaluation_metrix['value'],
                                                     metal_level_evaluation_metrix['lower_limit'],
                                                     metal_level_evaluation_metrix['upper_limit']):

            return (
                metal_level_evaluation_metrix['metal_rating']['name'],
                metric_key_value,
                metal_level_evaluation_metrix_list,
            )
        else:
            continue


def application_level_handle_sum_aggregation_strategy(metric_evaluation_strategy, parameter_list, service_list, metric_index):
    default_value = None
    type = None
    period = None

    period = "HALF_YEAR"
    period_value = len(service_list)
    metric_parameters_data = {}
    metric_data = {}
    month_wise_data = {}
    global_service = None
    default_metal_level_evaluation_matrix={}
    for parameter in parameter_list:
        parameter_name = parameter['name']
        parameter_value = 0
        service_count=0
        for service in service_list:
            try:
                parameter_value += service_list[service]["metric_index_data"][metric_index][
                    "overview"]["metric_parameter_data"][parameter_name]['value']
                global_service = service
                service_count+=1
            except Exception as e:
                parameter_value += 0
        parameter_value_avg = parameter_value
        service = global_service
        metal_rating_evaluation_list = service_list[service]["metric_index_data"][metric_index][
            "overview"]["metric_parameter_data"][parameter_name]['metal_rating_evaluation']

        metal_level, metal_value, metal_level_evaluation_metrix_list = evaluate_application_level_period_metal_value(
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


def application_level_handle_average_aggregation_strategy(metric_evaluation_strategy, parameter_list, service_list, metric_index):
    default_value = None
    type = None
    metric_parameters_data = {}
    metric_data = {}
    default_metal_level_evaluation_matrix={}
    for parameter in parameter_list:
        parameter_name = parameter['name']
        parameter_value = 0
        count=0
        for service in service_list:
            try:
                parameter_value += service_list[service]["metric_index_data"][metric_index][
                    "overview"]["metric_parameter_data"][parameter_name]['value']
                count+=1
            except Exception as e:
                parameter_value += 0
        try:
            parameter_value_avg = parameter_value/count
        except ZeroDivisionError as e:
            parameter_value_avg = parameter_value
        metal_rating_evaluation_list = parameter['metal_rating_evaluation']
        metal_level, metal_value = evaluate_metal_value(
            parameter_value_avg, metal_rating_evaluation_list)
        metric_parameters_data[parameter_name] = {
            'value': metal_value, 'level': metal_level, 'type': parameter['data_type']['name']}
        metric_parameters_data[parameter_name]['metal_rating_evaluation'] = metal_rating_evaluation_list
        # check and set default value for metric
        if parameter['default_display_parameter']:
            default_value = metal_value
            type = parameter['data_type']['name']
            default_metal_level_evaluation_matrix=get_rating_evaluation_in_human(metric_index,metal_rating_evaluation_list,type)

    # get paramter_json on the basis of strategy and set metal level of metric index
    metric_level = get_metric_level_metal_value(
        metric_evaluation_strategy, metric_parameters_data)
    metric_data['value'] = default_value
    metric_data["level"] = metric_level
    metric_data['type'] = type
    metric_data['rating']= default_metal_level_evaluation_matrix
    return metric_data, metric_parameters_data


def application_level_handle_month_sum_aggregation_strategy(metric_evaluation_strategy, parameter_list, service_list, metric_index, month):
    default_value = None
    type = None
    period = None

    period = "MONTH"
    period_value = len(service_list)
    metric_parameters_data = {}
    metric_data = {}
    month_wise_data = {}
    global_service = None
    count = 0
    default_metal_level_evaluation_matrix={}
    for parameter in parameter_list:
        parameter_name = parameter['name']

        parameter_value = 0
        for service in service_list:
            if metric_index not in service_list[service]["metric_index_data"]:
                continue
            if month in service_list[service]["metric_index_data"][metric_index]['month_wise_data']:
                count += 1
                parameter_value += service_list[service]["metric_index_data"][metric_index][
                    'month_wise_data'][month]["metric_parameter_data"][parameter_name]['value']
                global_service = service
        service = global_service
        if not count:
            raise InvalidMonthException(
                f"{month} no service has metric in this month")
        metal_rating_evaluation_list = service_list[service]["metric_index_data"][metric_index][
            'month_wise_data'][month]["metric_parameter_data"][parameter_name]['metal_rating_evaluation']
        metal_level, metal_value, metal_level_evaluation_metrix_list = evaluate_application_level_period_metal_value(
            parameter_value, metal_rating_evaluation_list, period, period_value)
        metric_parameters_data[parameter_name] = {}
        metric_parameters_data[parameter_name]['value'] = metal_value
        metric_parameters_data[parameter_name]['level'] = metal_level
        metric_parameters_data[parameter_name]['metal_rating_evaluation'] = metal_level_evaluation_metrix_list
        # check and set default value for metric
        if parameter['default_display_parameter']:
            default_value = metal_value
            type = parameter['data_type']['name']
            default_metal_level_evaluation_matrix=get_rating_evaluation_in_human(metric_index, metal_level_evaluation_metrix_list,type,period)

    # get paramter_json on the basis of strategy and set metal level of metric index
    metric_level = get_metric_level_metal_value(
        metric_evaluation_strategy, metric_parameters_data)
    metric_data['value'] = default_value
    metric_data["level"] = metric_level
    metric_data['type'] = type
    # metric_data['period']=period
    metric_data['rating']= default_metal_level_evaluation_matrix
    return metric_data, metric_parameters_data


def application_level_handle_month_average_aggregation_strategy(metric_evaluation_strategy, parameter_list, service_list, metric_index, month):
    default_value = None
    type = None
    metric_parameters_data = {}
    metric_data = {}
    default_metal_level_evaluation_matrix={}
    for parameter in parameter_list:
        parameter_name = parameter['name']
        parameter_value = 0
        count = 0
        for service in service_list:
            if metric_index in service_list[service]["metric_index_data"]:
                if month in service_list[service]["metric_index_data"][metric_index]['month_wise_data']:
                    count += 1
                    parameter_value += service_list[service]["metric_index_data"][metric_index][
                        'month_wise_data'][month]["metric_parameter_data"][parameter_name]['value']

        if not count:
            raise InvalidMonthException(
                f"{month} no service has metric in this month")
        try:
            parameter_value_avg = parameter_value/count
        except ZeroDivisionError as e:
            parameter_value_avg = parameter_value
        metal_rating_evaluation_list = parameter['metal_rating_evaluation']
        metal_level, metal_value = evaluate_metal_value(
            parameter_value_avg, metal_rating_evaluation_list)
        metric_parameters_data[parameter_name] = {
            'value': metal_value, 'level': metal_level, 'type': parameter['data_type']['name']}
        metric_parameters_data[parameter_name]['metal_rating_evaluation'] = metal_rating_evaluation_list
        # check and set default value for metric
        if parameter['default_display_parameter']:
            default_value = metal_value
            type = parameter['data_type']['name']
            default_metal_level_evaluation_matrix=get_rating_evaluation_in_human(metric_index,metal_rating_evaluation_list,type)

    # get paramter_json on the basis of strategy and set metal level of metric index
    metric_level = get_metric_level_metal_value(
        metric_evaluation_strategy, metric_parameters_data)
    metric_data['value'] = default_value
    metric_data["level"] = metric_level
    metric_data['type'] = type
    metric_data['rating']= default_metal_level_evaluation_matrix
    return metric_data, metric_parameters_data


def is_greater_than(group, index):
    metric_level_score_mapping_pick_highest = {
        "ELITE": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
    if metric_level_score_mapping_pick_highest[group['level']] > metric_level_score_mapping_pick_highest[index['level']]:
        return True
    else:
        return False


def is_smaller_than(group, index):
    metric_level_score_mapping_pick_highest = {
        "ELITE": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
    if metric_level_score_mapping_pick_highest[group['level']] < metric_level_score_mapping_pick_highest[index['level']]:
        return True
    else:
        return False


def add_level(group, index):
    if group['level'] in ["ELITE","HIGH","MEDIUM","LOW"]  and index['level'] in ["ELITE","HIGH","MEDIUM","LOW"]:
        return get_metal_score(group['level'])+get_metal_score(index['level'])
    elif type(group['level']) == int and index['level'] in ["ELITE","HIGH","MEDIUM","LOW"]:
        return group['level']+get_metal_score(index['level'])
    elif type(group['level']) == int and type(index['level']) == int:
        return group['level'] + index['level']
    else:
        return None
        


def set_group_level_for_average_stategy(org, app_name, service, application_service_dict, application_level_group_all, metric_group_metric_index_mapping, group):
    metric_index_data = application_service_dict[f"{org}.{app_name}.{service}"]["metric_index_data"]
    metric_group_data = application_level_group_all[f"{org}.{app_name}.{service}"]["metric_group_data"]
    for index in metric_group_metric_index_mapping[group]["index"]:
        if not metric_group_data[group]["overview"]:
            try:
                metric_group_data[group]["overview"] = copy.copy(
                    metric_index_data[index]["overview"]["metric_data"])
                metal_level = metric_group_data[group]["overview"]['level']
                metric_group_data[group]["overview"]['level'] = get_metal_score(metal_level)
            except Exception as e:
                continue
            for month in metric_index_data[index]["month_wise_data"]:
                metric_group_data[group]["month_wise_data"][month] = copy.copy(
                    metric_index_data[index]["month_wise_data"][month]["metric_data"])
                metal_level = metric_group_data[group]["month_wise_data"][month]['level']
                metric_group_data[group]["month_wise_data"][month]['level'] =  get_metal_score(metal_level)
        else:
            try:
                group_overview = metric_group_data[group]["overview"]
                index_overview = metric_index_data[index]["overview"]["metric_data"]
            except Exception as er:
                continue
            metric_group_data[group]["overview"]["level"] = add_level(
                group_overview, index_overview)
            for month in metric_index_data[index]["month_wise_data"]:

                if (month not in metric_group_data[group]["month_wise_data"]):
                    # For group metric but some metric don't have data in the month so setting by default 0
                    metric_group_data[group]["month_wise_data"][month] = {
                        "level": 0}
                group_month = metric_group_data[group]["month_wise_data"][month]
                index_month = metric_index_data[index]["month_wise_data"][month]["metric_data"]
                if index_month:
                    
                    metric_group_data[group]["month_wise_data"][month]["level"] = add_level(
                        group_month, index_month)
                else:
                    continue
    app_scores = metric_group_data[group]["overview"]["level"]
    metric_group_data[group]["overview"]["level"] = app_scores / \
        (len(metric_group_metric_index_mapping[group]["index"]))
    metal_score = metric_group_data[group]["overview"]["level"]

    metric_group_data[group]["overview"]["level"] = get_metal_name(metal_score)
    for month in metric_group_data[group]["month_wise_data"]:
        scores = metric_group_data[group]["month_wise_data"][month]["level"]

        metric_group_data[group]["month_wise_data"][month]["level"] = get_metal_name(
            scores / (len(metric_group_metric_index_mapping[group]["index"])))


def set_group_level_for_pick_lowest_strategy(org, app_name, service, application_service_dict, application_level_group_all, metric_group_metric_index_mapping, group):
    metric_index_data = application_service_dict[f"{org}.{app_name}.{service}"]["metric_index_data"]
    metric_group_data = application_level_group_all[f"{org}.{app_name}.{service}"]["metric_group_data"]
    for index in metric_group_metric_index_mapping[group]["index"]:
        if not metric_group_data[group]["overview"]:
            metric_group_data[group]["overview"] = copy.copy(
                metric_index_data[index]["overview"]["metric_data"])
            for month in metric_index_data[index]["month_wise_data"]:
                metric_group_data[group]["month_wise_data"][month] = copy.copy(
                    metric_index_data[index]["month_wise_data"][month]["metric_data"])
        else:
            try:
                group_overview = metric_group_data[group]["overview"]
                index_overview = metric_index_data[index]["overview"]["metric_data"]
            except Exception as er:
                continue
            if not is_smaller_than(group_overview, index_overview):
                metric_group_data[group]["overview"] = metric_index_data[index]["overview"]["metric_data"]
            for month in metric_index_data[index]["month_wise_data"]:
                group_month = metric_group_data[group]["month_wise_data"][month]
                index_month = metric_index_data[index]["month_wise_data"][month]["metric_data"]
                if not is_smaller_than(group_month, index_month):
                    metric_group_data[group]["month_wise_data"][month] = copy.copy(
                        metric_index_data[index]["month_wise_data"][month]["metric_data"])


def set_group_level_for_pick_highest_strategy(org, app_name, service, application_service_dict, application_level_group_all, metric_group_metric_index_mapping, group):
    metric_index_data = application_service_dict[f"{org}.{app_name}.{service}"]["metric_index_data"]
    metric_group_data = application_level_group_all[f"{org}.{app_name}.{service}"]["metric_group_data"]
    for index in metric_group_metric_index_mapping[group]["index"]:
        if not metric_group_data[group]["overview"]:
            metric_group_data[group]["overview"] = copy.copy(
                metric_index_data[index]["overview"]["metric_data"])
            for month in metric_index_data[index]["month_wise_data"]:
                metric_group_data[group]["month_wise_data"][month] = copy.copy(
                    metric_index_data[index]["month_wise_data"][month]["metric_data"])
        else:
            try:
                group_overview = metric_group_data[group]["overview"]
                index_overview = metric_index_data[index]["overview"]["metric_data"]
            except Exception as e:
                continue
            if not is_greater_than(group_overview, index_overview):
                metric_group_data[group]["overview"] = copy.copy(
                    metric_index_data[index]["overview"]["metric_data"])
            for month in metric_index_data[index]["month_wise_data"]:
                group_month = metric_group_data[group]["month_wise_data"][month]
                index_month = metric_index_data[index]["month_wise_data"][month]["metric_data"]
                if not is_greater_than(group_month, index_month):
                    metric_group_data[group]["month_wise_data"][month] = copy.copy(
                        metric_index_data[index]["month_wise_data"][month]["metric_data"])


def prepare_application_level_service_metric_group_data(org, app_name, service, application_service_dict, application_level_group_all, metric_group_metric_index_mapping):

    for group in metric_group_metric_index_mapping:
        if f"{org}.{app_name}.{service}" not in application_level_group_all:
            application_level_group_all[f"{org}.{app_name}.{service}"] = {
                "metric_group_data": {}
            }
            application_level_group_all[f"{org}.{app_name}.{service}"]["metric_group_data"][group] = {
                "overview": {}, "month_wise_data": {}}
        else:
            application_level_group_all[f"{org}.{app_name}.{service}"]["metric_group_data"][group] = {
                "overview": {}, "month_wise_data": {}}
            # metal rating evaluation for group strategy
            # group has strategy PICK_HIGHEST,PICK_LOWEST and AVERAGE
        if metric_group_metric_index_mapping[group]["strategy"] == "PICK_HIGHEST":
            set_group_level_for_pick_highest_strategy(
                org, app_name, service, application_service_dict, application_level_group_all, metric_group_metric_index_mapping, group)

        elif metric_group_metric_index_mapping[group]["strategy"] == "PICK_LOWEST":
            set_group_level_for_pick_lowest_strategy(
                org, app_name, service, application_service_dict, application_level_group_all, metric_group_metric_index_mapping, group)

        elif metric_group_metric_index_mapping[group]["strategy"] == "AVERAGE":
            set_group_level_for_average_stategy(
                org, app_name, service, application_service_dict, application_level_group_all, metric_group_metric_index_mapping, group)


def prepare_application_level_service_metric_index_data(org, app_name, service, application_service_dict, month_name_list, application_service_index_mapping, metric_index_serialized_data):
    metric_wise_month_list = month_name_list

    # TODO send the list of impacted indexes only as only they will be impacted and updated

    for metric_index_instance in application_service_index_mapping[f"{org}.{app_name}.{service}"]:
        # calculating metal rating over a 6 month
        metric_index_dict = metric_index_serialized_data[metric_index_instance]
        parameter_dict = metric_index_dict['metric_parameters']
        if metric_index_dict['metric_aggregation_strategy']['name'] == "PER_PERIOD":
            metric_data, metric_parameter_data = prepare_across_month_handle_sum_aggregation_strategy(
                org, app_name, service, metric_index_dict['metric_evaluation_strategy']['name'], parameter_dict, metric_wise_month_list, application_service_dict, metric_index_instance)
        elif metric_index_dict['metric_aggregation_strategy']['name'] == "PER_SCAN":
            metric_data, metric_parameter_data = prepare_across_month_handle_average_aggregation_strategy(
                org, app_name, service, metric_index_dict['metric_evaluation_strategy']['name'], parameter_dict, metric_wise_month_list, application_service_dict, metric_index_instance)

        if (metric_index_instance not in application_service_dict[f"{org}.{app_name}.{service}"]["metric_index_data"]):
            application_service_dict[f"{org}.{app_name}.{service}"]["metric_index_data"][metric_index_instance] = {
                "overview": {}, "month_wise_data": {}}
            application_service_dict[f"{org}.{app_name}.{service}"]["metric_index_data"][
                metric_index_instance]["overview"]["metric_data"] = metric_data
            application_service_dict[f"{org}.{app_name}.{service}"]["metric_index_data"][
                metric_index_instance]["overview"]["metric_parameter_data"] = metric_parameter_data
        else:
            application_service_dict[f"{org}.{app_name}.{service}"]["metric_index_data"][metric_index_instance]['overview'] = {
                "metric_data": {}, "metric_parameter_data": {}}
            application_service_dict[f"{org}.{app_name}.{service}"]["metric_index_data"][
                metric_index_instance]["overview"]["metric_data"] = metric_data
            application_service_dict[f"{org}.{app_name}.{service}"]["metric_index_data"][
                metric_index_instance]["overview"]["metric_parameter_data"] = metric_parameter_data


def prepare_application_level_service_data(org, app_name, service, metric_group_metric_index_mapping, application_service_index_mapping, metric_index_serialized_data):

    application_service_dict = cache.get(
        f"application_level_all_service_data.{org}.{app_name}", {})
    # application_index_mapping = cache.get(f"application_index_mapping.{org}.{app_name}",set())
    month_list_set = cache.get(f"month_set.{org}.{app_name}", set())
    application_level_group_all = cache.get(
        f"application_level_all_group_data.{org}.{app_name}", {})
    month_name_list = get_next_six_month_and_year_names()

    prepare_application_level_service_metric_index_data(org=org,
                                                        app_name=app_name,
                                                        service=service,
                                                        application_service_dict=application_service_dict,
                                                        month_name_list=month_name_list,
                                                        application_service_index_mapping=application_service_index_mapping,
                                                        metric_index_serialized_data=metric_index_serialized_data,
                                                        )
    prepare_application_level_service_metric_group_data(org=org,
                                                        app_name=app_name,
                                                        service=service,
                                                        application_service_dict=application_service_dict,
                                                        application_level_group_all=application_level_group_all,
                                                        metric_group_metric_index_mapping=metric_group_metric_index_mapping,
                                                        )

    cache.set(
        f"application_level_all_service_data.{org}.{app_name}", application_service_dict)
    # cache.set(f"application_index_mapping.{org}.{app_name}", application_index_mapping)
    cache.set(f"month_set.{org}.{app_name}", month_list_set)

    cached_metric_group_metric_index_mapping = cache.get(
        f"metric_group_metric_index_mapping.{org}.{app_name}", {})
    if cached_metric_group_metric_index_mapping:
        metric_group_metric_index_mapping.update(
            cache.get(f"metric_group_metric_index_mapping.{org}.{app_name}"))
    cache.set(
        f"metric_group_metric_index_mapping.{org}.{app_name}", metric_group_metric_index_mapping)
    cache.set(
        f"application_level_all_group_data.{org}.{app_name}", application_level_group_all)


def set_month_data_to_service_cache(app, month_wise_metric_data):
    app_name = app.application
    org = app.organization
    service = app.service
    application_service_dict = cache.get(
        f"application_level_all_service_data.{org}.{app_name}", {})
    application_index_mapping = cache.get(
        f"application_index_mapping.{org}.{app_name}", set())

    if f"{org}.{app_name}.{service}" not in application_service_dict:
        application_service_dict[f"{org}.{app_name}.{service}"] = {
            "metric_index_data": {}}
    month_name_list = get_next_six_month_and_year_names()
    for metric_index in month_wise_metric_data:
        if metric_index not in application_service_dict[f"{org}.{app_name}.{service}"]["metric_index_data"]:
            application_service_dict[f"{org}.{app_name}.{service}"]["metric_index_data"][metric_index] = {
            }
        if 'month_wise_data' not in application_service_dict[f"{org}.{app_name}.{service}"]["metric_index_data"][metric_index]:
            application_service_dict[f"{org}.{app_name}.{service}"]["metric_index_data"][metric_index] = {
                "month_wise_data": {}}
        application_service_dict[f"{org}.{app_name}.{service}"]["metric_index_data"][metric_index]["month_wise_data"].update(
            month_wise_metric_data[metric_index])
        application_index_mapping.add(metric_index)

        service_month_list = list(
            application_service_dict[f"{org}.{app_name}.{service}"]["metric_index_data"][metric_index]["month_wise_data"].keys())

        for month in service_month_list:
            if month not in month_name_list:
                application_service_dict[f"{org}.{app_name}.{service}"]["metric_index_data"][metric_index]["month_wise_data"].pop(
                    month)

    cache.set(
        f"application_level_all_service_data.{org}.{app_name}", application_service_dict)
    cache.set(
        f"application_index_mapping.{org}.{app_name}", application_index_mapping)
    cache.set(f"month_set.{org}.{app_name}", month_name_list)


def get_data_from_cache(key):
    return cache.get(key)


def get_all_key_cache_data(keys):
    # parallel get is remove due to some thread pool issue
    s = []
    for key in keys:
        s.append(cache.get(key))
    return tuple(s)


def set_application_level_metric_group_data(org, app_name, application_service, application_level_service_group_data, app_group_data, service_count, month_set, group):
    for month in month_set:
        # calculating average
        mon_score = 0
        level_score = 0
        for service in application_service:
            try:
                level = application_level_service_group_data[service][
                    "metric_group_data"][group]["overview"]["level"]
                value=get_metal_score(level)
                if value:
                    level_score += get_metal_score(level)
            except Exception as e:
                continue

            try:
                mon = application_level_service_group_data[service][
                    "metric_group_data"][group]["month_wise_data"][month]["level"]
            except Exception as e:
                continue
            else:
                mon_value=get_metal_score(mon)
                if mon_value:
                    mon_score += mon_value
        if group not in app_group_data[f"{org}.{app_name}"]["metric_group_data"]:
            app_group_data[f"{org}.{app_name}"]["metric_group_data"][group] = {
                "overview": {},
                "month_wise_data": {},
            }
            app_group_data[f"{org}.{app_name}"]["metric_group_data"][group]["overview"]["level"] = get_metal_name(
                level_score / service_count)
            app_group_data[f"{org}.{app_name}"]["metric_group_data"][group]["month_wise_data"][month] = {
            }
            app_group_data[f"{org}.{app_name}"]["metric_group_data"][group]["month_wise_data"][month]["level"] = get_metal_name(
                mon_score / service_count)
        else:
            app_group_data[f"{org}.{app_name}"]["metric_group_data"][group]["month_wise_data"][month] = {
            }
            app_group_data[f"{org}.{app_name}"]["metric_group_data"][group]["month_wise_data"][month]["level"] = get_metal_name(
                mon_score / service_count)
def get_days_hours_with_minutes(value):
    total_hours = math.ceil(int(value) / 60)
                        # Convert hours to days and hours
    days = total_hours // 24
    remaining_hours = total_hours % 24
    return days,remaining_hours
def get_formatted_strings(name,value,upper_limit,lower_limit,period_name=None):
    if period_name is not None:
        
        if value is None:
            return f"{name} {value} Per {period_name}"
        else:
            return f" {name} Between {upper_limit} and {lower_limit} Per {period_name}"
    else:
        if value is None:
            return f"{name} is {value} "
        else:
            return f" {name} Between {upper_limit} and {lower_limit} "
        
def get_rating_evolution(overview,metric_index,application_service_count):
    metric_index_instance=MetricGroupIndex.objects.get(name=metric_index)

    metric_parameters=metric_index_instance.metric_parameters.all()
    rating_dict={}
    if metric_index_instance:
        for i in metric_parameters:
            metal_rating_evolution_rating=i.metal_rating_evaluation.all()
            for rating in metal_rating_evolution_rating:
                if overview['metric_data']['type']=='INT':
                    d={}
                    if rating.period:
                    
                        if rating.value!=None:
                            scaled_value=float(rating.value)*application_service_count
                            d[rating.metal_rating.name]=f"{metric_index_instance.name} Per {rating.period.name.title()} {scaled_value} "
                        else:
                            scaled_upper_limit=float(rating.upper_limit)*application_service_count
                            scaled_lower_limit=float(rating.lower_limit)*application_service_count
                            d[rating.metal_rating.name]=f" {metric_index_instance.name} Per {rating.period.name.title()} {scaled_lower_limit} - {scaled_upper_limit} "
                    else:
                        if rating.value!=None:
                            scaled_value=float(rating.value)*application_service_count
                            d[rating.metal_rating.name]=f"{metric_index_instance.name} value is {' '.join(rating.operator.name.split('_')).title()} {scaled_value} "
                        else:
                            scaled_upper_limit=float(rating.upper_limit)*application_service_count
                            scaled_lower_limit=float(rating.lower_limit)*application_service_count
                            d[rating.metal_rating.name]=f" {metric_index_instance.name} value between {scaled_lower_limit} - {scaled_upper_limit} "
                    rating_dict.update(d)
                elif overview['metric_data']['type']=='PERCENTAGE':
                    d={}
                    if rating.value!=None :
                        if rating.operator.name in ('LESS_THAN','LESS_THAN_EQUAL_TO'):
                            d[rating.metal_rating.name]=f"0% - {rating.value}%"
                        else:
                            d[rating.metal_rating.name]=f"{rating.value}% - 100%"
                    else:
                        d[rating.metal_rating.name]=f"{rating.lower_limit}% - {rating.upper_limit}%"
                    rating_dict.update(d)
                elif overview['metric_data']['type']=='TIME':
                    d={}
                    if rating.value!=None:
                        days,hours=get_days_hours_with_minutes(rating.value)
                        if rating.metal_rating.name=='ELITE':
                            d[rating.metal_rating.name]=f"Less Than {days} days , {math.ceil(hours)} Hours"
                        if rating.metal_rating.name=='LOW':
                            d[rating.metal_rating.name]=f"Greater Than {days} days , {math.ceil(hours)} Hours"
                    else:
                        upper_limit_days,upper_limit_hours=get_days_hours_with_minutes(rating.upper_limit)
                        lower_limit_days,lower_limit_hours=get_days_hours_with_minutes(rating.lower_limit)
                        d[rating.metal_rating.name]=f"Between {upper_limit_days} days ,{math.ceil(upper_limit_hours)} hrs and {lower_limit_days} days, {math.ceil(lower_limit_hours)} hrs"
                    rating_dict.update(d)
    
    return rating_dict

def set_application_level_metric_index_data(org, app_name, application_service, month_list_set, app_metric_index_data, metric_index, parameter_list, metric_index_serialized_data):
    metric_index_dict = metric_index_serialized_data[metric_index]
    if metric_index_dict['metric_aggregation_strategy']['name'] == "PER_PERIOD":
        metric_data, metric_parameter_data = application_level_handle_sum_aggregation_strategy(metric_index_dict['metric_evaluation_strategy']['name'],
                                                                                               parameter_list,
                                                                                               application_service,
                                                                                               metric_index,
                                                                                               )
    elif metric_index_dict['metric_aggregation_strategy']['name'] == "PER_SCAN":
        metric_data, metric_parameter_data = application_level_handle_average_aggregation_strategy(metric_index_dict['metric_evaluation_strategy']['name'],
                                                                                                   parameter_list,
                                                                                                   application_service,
                                                                                                   metric_index,
                                                                                                   )

    if (metric_index not in app_metric_index_data[f"{org}.{app_name}"]["metric_index_data"]):
        app_metric_index_data[f"{org}.{app_name}"]["metric_index_data"][metric_index] = {
            "month_wise_data": {}, "overview": {}}
        app_metric_index_data[f"{org}.{app_name}"]["metric_index_data"][metric_index]["overview"]["metric_data"] = metric_data
        app_metric_index_data[f"{org}.{app_name}"]["metric_index_data"][
            metric_index]["overview"]["metric_parameter_data"] = metric_parameter_data
        app_metric_index_data[f"{org}.{app_name}"]["metric_index_data"][
            metric_index]["overview"]["rating"]=get_rating_evolution(app_metric_index_data[f"{org}.{app_name}"]["metric_index_data"][metric_index]["overview"],metric_index,application_service_count=len(application_service))

    for month in month_list_set:
        try:

            if metric_index_dict['metric_aggregation_strategy']['name'] == "PER_PERIOD":
                metric_data, metric_parameter_data = application_level_handle_month_sum_aggregation_strategy(metric_index_dict['metric_evaluation_strategy']['name'],
                                                                                                             parameter_list,
                                                                                                             application_service,
                                                                                                             metric_index,
                                                                                                             month,
                                                                                                             )
            elif metric_index_dict['metric_aggregation_strategy']['name'] == "PER_SCAN":
                metric_data, metric_parameter_data = application_level_handle_month_average_aggregation_strategy(metric_index_dict['metric_evaluation_strategy']['name'],
                                                                                                                 parameter_list,
                                                                                                                 application_service,
                                                                                                                 metric_index,
                                                                                                                 month)
        except InvalidMonthException as e:
            print(str(e))
            continue
        except Exception as e:
            print(str(e))
            continue
        else:
            if (month not in app_metric_index_data[f"{org}.{app_name}"]["metric_index_data"][metric_index]["month_wise_data"]):
                app_metric_index_data[f"{org}.{app_name}"]["metric_index_data"][metric_index]["month_wise_data"][month] = {
                }
                app_metric_index_data[f"{org}.{app_name}"]["metric_index_data"][
                    metric_index]["month_wise_data"][month]["metric_data"] = metric_data
                app_metric_index_data[f"{org}.{app_name}"]["metric_index_data"][metric_index][
                    "month_wise_data"][month]["metric_parameter_data"] = metric_parameter_data


def prepare_application_level_data_and_set_cache(app_name, metric_index_serialized_data, application_index_mapping, organization_name="bp"):
    org = organization_name

    # Define the keys you want to retrieve from the cache
    cache_keys = [
        f"application_level_all_service_data.{org}.{app_name}",
        f"application_level_all_group_data.{org}.{app_name}",
        f"metric_group_metric_index_mapping.{org}.{app_name}",
        f"month_set.{org}.{app_name}",
        f"organization_level_all_application_mapping.{org}"
    ]

    (
        application_service,
        application_level_group_all,
        metric_group_metric_index_mapping,
        month_list_set,
        organization_level_all_application
    ) = get_all_key_cache_data(cache_keys)

    app_metric_index_data = {f"{org}.{app_name}": {"metric_index_data": {}}}
    app_metric_group_data = {f"{org}.{app_name}": {"metric_group_data": {}}}
    # calculating overview and month wise for application across the service
    # by using strategy to scale to service_count * days_in_6_month
    service_count = len(application_service)
    for metric_index_instance in application_index_mapping[f"{org}.{app_name}"]:
        parameter_list = metric_index_serialized_data[metric_index_instance]['metric_parameters']

        set_application_level_metric_index_data(org, app_name, application_service, month_list_set,
                                                app_metric_index_data, metric_index_instance, parameter_list, metric_index_serialized_data)

        app_metric_index_data[f"{org}.{app_name}"]['metric_service_count'] = service_count
    # group metric at application level
    for group in metric_group_metric_index_mapping:
        set_application_level_metric_group_data(
            org, app_name, application_service, application_level_group_all, app_metric_group_data, service_count, month_list_set, group)

    app_metric_group_data[f"{org}.{app_name}"]['metric_service_count'] = service_count
    cached_app_metric_index_data = cache.get(
        f"{org}.{app_name}.index_level", {})
    if f"{org}.{app_name}" in cached_app_metric_index_data:
        cached_app_metric_index_data[f"{org}.{app_name}"]['metric_index_data'].update(
            app_metric_index_data[f"{org}.{app_name}"]['metric_index_data'])
    else:
        cached_app_metric_index_data[f"{org}.{app_name}"] = {}
        cached_app_metric_index_data[f"{org}.{app_name}"][
            'metric_index_data'] = app_metric_index_data[f"{org}.{app_name}"]['metric_index_data']

    cache.set(f"{org}.{app_name}.index_level", cached_app_metric_index_data)
    if not organization_level_all_application:
        organization_level_all_application=[]
    if f"{org}.{app_name}.index_level" not in organization_level_all_application:
        organization_level_all_application.append(f"{org}.{app_name}.index_level")
    cached_app_metric_group_data = cache.get(
        f"{org}.{app_name}.group_level", {})
    if f"{org}.{app_name}" in cached_app_metric_group_data:
        cached_app_metric_group_data[f"{org}.{app_name}"]['metric_group_data'].update(
            app_metric_group_data[f"{org}.{app_name}"]['metric_group_data'])
    else:
        cached_app_metric_group_data[f"{org}.{app_name}"] = {}
        cached_app_metric_group_data[f"{org}.{app_name}"][
            'metric_group_data'] = app_metric_group_data[f"{org}.{app_name}"]['metric_group_data']

    cache.set(f"{org}.{app_name}.group_level", cached_app_metric_group_data)
    cache.set(f"organization_level_all_application_mapping.{org}",organization_level_all_application)


def get_application_level_service_data(metric_group, app_name, organization_name="bp"):
    org = organization_name
    if app_name == 'all':
        return {}

    # Define the keys you want to retrieve from the cache
    cache_keys = [
        f"application_level_all_service_data.{org}.{app_name}"
    ]

    (application_service,) = get_all_key_cache_data(cache_keys)

    app_level_index_data = cache.get(f"{org}.{app_name}.index_level")
    app_level_group_data = cache.get(f"{org}.{app_name}.group_level")
    service_count = len(application_service)
    if metric_group == 'all':
        return app_level_group_data
    else:

        metric_group_indexes = MetricGroupIndex.objects.filter(
            metric_group__name=metric_group)
        response_json = {}
        index_data = None
        key = f'{organization_name}.{app_name}'
        response_json[key] = {'metric_index_data': {}}
        for index in metric_group_indexes:
            try:
                index_data = app_level_index_data[key]['metric_index_data'][index.name]
                response_json[key]['metric_index_data'][index.name] = {}
                response_json[key]['metric_index_data'][index.name].update(
                    index_data)
                response_json[key]['metric_index_data'][index.name]['description']=index.description
                response_json[key]['metric_index_data'][index.name]['icon']=index.icon
                
            except Exception as e:
                continue
        response_json[key]['metric_service_count'] = service_count
        return response_json


def get_service_level_data(metric_group, app_name, organization_name="bp"):
    org = organization_name
    if app_name == 'all':
        return {}

    cache_keys = [
        f"application_level_all_service_data.{org}.{app_name}",
        f"application_level_all_group_data.{org}.{app_name}",
        f"metric_group_metric_index_mapping.{org}.{app_name}",
        f"month_set.{org}.{app_name}",
    ]

    (
        application_service,
        application_level_group_all,
        metric_group_metric_index_mapping,
        month_list_set,
    ) = get_all_key_cache_data(cache_keys)

    app_level_index_data = cache.get(f"{org}.{app_name}.index_level")
    app_level_group_data = cache.get(f"{org}.{app_name}.group_level")
    service_count = len(application_service)

    if metric_group == 'all':
        app_json = {}
        app_key = f"{org}.{app_name}"
        app_json[app_key] = {'metric_group_data': {}}
        metric_group_obj = MetricGroup.objects.filter()
        for group in metric_group_obj:
            if group.name in app_level_group_data[app_key]['metric_group_data']:
                index_data = app_level_group_data[app_key]['metric_group_data'][group.name]
            else:
                continue
            app_json[app_key]['metric_group_data'][group.name] = {}
            app_json[app_key]['metric_group_data'][group.name].update(
                index_data)
        # app_json
        app_json[app_key]['metric_service_count'] = service_count
        application_level_group_all.update(app_json)
        return application_level_group_all
    else:
        response_json = {}
        app_json = {}
        services = ApplicationServiceMapping.objects.filter(
            application_name=app_name)
        for service in services:
            metric_group_indexes = MetricGroupIndex.objects.filter(
                metric_group__name=metric_group)

            index_data = None
            key = f'{organization_name}.{app_name}.{service.service_name}'
            response_json[key] = {'metric_index_data': {}}
            for index in metric_group_indexes:
                try:
                    index_data = application_service[key]['metric_index_data'][index.name]
                    response_json[key]['metric_index_data'][index.name] = {}
                    response_json[key]['metric_index_data'][index.name].update(
                        index_data)
                except Exception as e:
                    continue
        app_key = f"{org}.{app_name}"
        app_json[app_key] = {'metric_index_data': {}}
        metric_group_indexes = MetricGroupIndex.objects.filter(
            metric_group__name=metric_group)
        for index in metric_group_indexes:
            try:
                index_data = app_level_index_data[app_key]['metric_index_data'][index.name]
                app_json[app_key]['metric_index_data'][index.name] = {}
                app_json[app_key]['metric_index_data'][index.name].update(
                    index_data)
            except Exception as e:
                continue
        app_json[app_key]['metric_service_count'] = service_count
        response_json.update(app_json)
        return response_json


def prepare_org_month_average_aggregation_strategy(org_application_list, metric_index, parameter_list, metric_evaluation_strategy, month):
    default_value = None
    type = None
    metric_parameters_data = {}
    metric_data = {}
    default_metal_level_evaluation_matrix={}    
    for parameter in parameter_list:
        parameter_name = parameter['name']
        parameter_value = 0
        count = 0
        for service in org_application_list:
            if metric_index in org_application_list[service]["metric_index_data"]:
                if month in org_application_list[service]["metric_index_data"][metric_index]['month_wise_data']:
                    count += 1
                    parameter_value += org_application_list[service]["metric_index_data"][metric_index][
                                        'month_wise_data'][month]["metric_parameter_data"][parameter_name]['value']

        if not count:
            raise InvalidMonthException(
                                f"{month} no service has metric in this month")
        try:
            parameter_value_avg = parameter_value/count
        except ZeroDivisionError as e:
            parameter_value_avg = parameter_value
        metal_rating_evaluation_list = parameter['metal_rating_evaluation']
        metal_level, metal_value = evaluate_metal_value(
                            parameter_value_avg, metal_rating_evaluation_list)
        metric_parameters_data[parameter_name] = {
                            'value': metal_value, 'level': metal_level, 'type': parameter['data_type']['name']}
        metric_parameters_data[parameter_name]['metal_rating_evaluation'] = metal_rating_evaluation_list
                        # check and set default value for metric
        if parameter['default_display_parameter']:
            default_value = metal_value
            type = parameter['data_type']['name']
            default_metal_level_evaluation_matrix=get_rating_evaluation_in_human(metric_index,metal_rating_evaluation_list,type)
            
    # get paramter_json on the basis of strategy and set metal level of metric index
    metric_level = get_metric_level_metal_value(
                        metric_evaluation_strategy, metric_parameters_data)
    metric_data['value'] = default_value
    metric_data["level"] = metric_level
    metric_data['type'] = type
    metric_data['rating']= default_metal_level_evaluation_matrix
    return metric_parameters_data,metric_data

def prepare_org_month_sum_aggregation_strategy(org_application_list, metric_index, parameter_list, metric_evaluation_strategy, metric_parameters_data, metric_data, month):
    default_value = None
    type = None
    period = None

    period = "MONTH"
    period_value = len(org_application_list)
    month_wise_data = {}
    global_service = None
    count = 0
    default_metal_level_evaluation_matrix={}
    for parameter in parameter_list:
        parameter_name = parameter['name']

        parameter_value = 0
        for service in org_application_list:
            if metric_index not in org_application_list[service]["metric_index_data"]:
                continue
            if month in org_application_list[service]["metric_index_data"][metric_index]['month_wise_data']:
                count += 1
                parameter_value += org_application_list[service]["metric_index_data"][metric_index][
                                    'month_wise_data'][month]["metric_parameter_data"][parameter_name]['value']
                global_service = service
        service = global_service
        if not count:
            raise InvalidMonthException(
                                f"{month} no service has metric in this month")
        metal_rating_evaluation_list = org_application_list[service]["metric_index_data"][metric_index][
                            'month_wise_data'][month]["metric_parameter_data"][parameter_name]['metal_rating_evaluation']
        metal_level, metal_value, metal_level_evaluation_metrix_list = evaluate_application_level_period_metal_value(
                            parameter_value, metal_rating_evaluation_list, period, period_value)
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

def prepare_org_level_average_aggregation_strategy(org_application_list, metric_index_instance, parameter_list, metric_evaluation_strategy, metric_parameters_data, metric_data):
    default_value = None
    type = None
    default_metal_level_evaluation_matrix={}
    for parameter in parameter_list:
        parameter_name = parameter['name']
        parameter_value = 0
        count=0
        for application in org_application_list:
            if metric_index_instance.name not in org_application_list[application]["metric_index_data"]:
                continue
            try:
                parameter_value += org_application_list[application]["metric_index_data"][metric_index_instance.name][
                            "overview"]["metric_parameter_data"][parameter_name]['value']
                count+=1
            except Exception as e:
                parameter_value += 0
        if count == 0:
            raise InvalidApplicationException(f"No data available for {metric_index_instance.name} at application")
        try:
            parameter_value_avg = parameter_value/count
        except ZeroDivisionError as e:
            parameter_value_avg = parameter_value
        metal_rating_evaluation_list = parameter['metal_rating_evaluation']
        metal_level, metal_value = evaluate_metal_value(
                    parameter_value_avg, metal_rating_evaluation_list)
        metric_parameters_data[parameter_name] = {
                    'value': metal_value, 'level': metal_level, 'type': parameter['data_type']['name']}
        metric_parameters_data[parameter_name]['metal_rating_evaluation'] = metal_rating_evaluation_list
                # check and set default value for metric
        if parameter['default_display_parameter']:
            default_value = metal_value
            type = parameter['data_type']['name']
            default_metal_level_evaluation_matrix=get_rating_evaluation_in_human(metric_index_instance.name,metal_rating_evaluation_list,type)

    # get paramter_json on the basis of strategy and set metal level of metric index
    metric_level = get_metric_level_metal_value(
                metric_evaluation_strategy, metric_parameters_data)
    metric_data['value'] = default_value
    metric_data["level"] = metric_level
    metric_data['type'] = type
    metric_data['rating']= default_metal_level_evaluation_matrix

def prepare_org_level_sum_aggregation_strategy(organization_level_all_application, org_application_list, metric_index_instance, parameter_list, metric_evaluation_strategy, metric_parameters_data, metric_data):
    default_value = None
    type = None
    period = None

    period = "HALF_YEAR"
    period_value = len(organization_level_all_application)
    month_wise_data = {}
    global_service = None
    for parameter in parameter_list:
        parameter_name = parameter['name']
        parameter_value = 0
        application_count=0
        for application in org_application_list:
            if metric_index_instance.name not in org_application_list[application]["metric_index_data"]:
                continue
            try:
                parameter_value += org_application_list[application]["metric_index_data"][metric_index_instance.name][
                            "overview"]["metric_parameter_data"][parameter_name]['value']
                global_service = application
                application_count+=1
            except Exception as e:
                parameter_value += 0
        if application_count==0:
            raise InvalidApplicationException(f"not a valid data for {metric_index_instance.name} at application")
        parameter_value_avg = parameter_value
        application = global_service
        metal_rating_evaluation_list = org_application_list[application]["metric_index_data"][metric_index_instance.name][
                    "overview"]["metric_parameter_data"][parameter_name]['metal_rating_evaluation']

        metal_level, metal_value, metal_level_evaluation_metrix_list = evaluate_application_level_period_metal_value(
                    parameter_value_avg, metal_rating_evaluation_list, period, period_value)
        
        metric_parameters_data[parameter_name] = {}
        metric_parameters_data[parameter_name]['value'] = metal_value
        metric_parameters_data[parameter_name]['level'] = metal_level
        metric_parameters_data[parameter_name]['metal_rating_evaluation'] = metal_level_evaluation_metrix_list
                # check and set default value for metric
        if parameter['default_display_parameter']:
            default_value = metal_value
            type = parameter['data_type']['name']
            default_metal_level_evaluation_matrix=get_rating_evaluation_in_human(metric_index_instance.name,metal_level_evaluation_metrix_list,type,period)
            # get paramter_json on the basis of strategy and set metal level of metric index
    metric_level = get_metric_level_metal_value(
                metric_evaluation_strategy, metric_parameters_data)
    metric_data['value'] = default_value
    metric_data["level"] = metric_level
    metric_data['type'] = type
    # metric_data['period']=period
    metric_data['rating']= default_metal_level_evaluation_matrix


def get_application_data(metric_group, organization_name="bp"):
    unique_set = set()
    if metric_group == 'all':
        apps = ApplicationServiceMapping.objects.filter(
            organization=organization_name)
        for app in apps:
            unique_set.add(app.application_name)
        response_json = {}

        for app_name in unique_set:
            app_data = {}
            print(app_name)
            response = get_application_level_service_data(
                metric_group, app_name, organization_name)
            if response:
                app_data[f'{organization_name}.{app_name}'] = response.pop(
                f'{organization_name}.{app_name}')
            # app_data=response.pop(f'bp.{app_name}')

                response_json.update(app_data)
            
        return response_json
    else:
        apps = ApplicationServiceMapping.objects.filter(
            organization=organization_name)
        for app in apps:
            unique_set.add(app.application_name)
        response_json = {}

        for app_name in unique_set:
            try:
                app_data = {}
                response = get_application_level_service_data(
                    metric_group, app_name, organization_name)
                app_data[f'{organization_name}.{app_name}'] = response.pop(
                    f'{organization_name}.{app_name}')
                # app_data=response.pop(f'bp.{app_name}')

                response_json.update(app_data)

            except Exception as e:
                continue
        return response_json

def cache_all_data():
    for app_instance in ApplicationServiceMapping.objects.all():
        application = app_instance.application
        organization = app_instance.organization
        service = app_instance.service
        metric_group_index_mapping = cache.get(
            "metric_group_index_mapping", {})

        application_service_index_mapping = cache.get(
            "application_service_index_mapping",
            {f"{organization}.{application}.{service}": []},
        )
        service_level_metric_group_list = {}
        application_index_mapping = {f"{organization}.{application}": []}
        month_wise_metric_data = {}
        metric_index_serialized_data = {}
        for month in app_instance.monthwise_metric.all():
            metric_index_instance_serialized_data = cache.get(
                month.metric_group_index.name
            )
            metric_index_serialized_data[month.metric_group_index.name] = (
                metric_index_instance_serialized_data
            )
            if (
                month.metric_group_index.name
                not in application_service_index_mapping[
                    f"{organization}.{application}.{service}"
                ]
            ):
                application_service_index_mapping[
                    f"{organization}.{application}.{service}"
                ].append(month.metric_group_index.name)

            if (
                month.metric_group_index.name
                not in application_index_mapping[f"{organization}.{application}"]
            ):
                application_index_mapping[f"{organization}.{application}"].append(
                    month.metric_group_index.name
                )
            set_metric_index_month_data(
                month_wise_metric_data, month.metric_group_index, month
            )
            prepare_service_level_metric_group_metric_index_mapping(
                metric_group_index_mapping,
                service_level_metric_group_list,
                month.metric_group_index,
            )

        set_month_data_to_service_cache(app_instance, month_wise_metric_data)
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

from rest_framework.utils import model_meta
import os
def update_model_fields(instance, validated_data):
    info = model_meta.get_field_info(instance)
    m2m_fields = []
    for attr, value in validated_data.items():
        if attr in info.relations and info.relations[attr].to_many:
            m2m_fields.append((attr, value))
        else:
            setattr(instance, attr, value)
    instance.save()
    for attr, value in m2m_fields:
        field = getattr(instance, attr)
        field.set(value)



def store_file(base64_encode_content, file_path, file_name):
    try:
        os.makedirs(file_path, exist_ok=True)
        file_content = base64.b64decode(base64_encode_content)
        file_path_with_name = os.path.join(file_path, file_name)
        with open(file_path_with_name, "w") as file:
            file.write(file_content.decode("utf-8"))
        return file_name
    except Exception as error:
        LOGGER.error("Error in file store on file_path_with_name: " + str(file_path)+"/"+str(file_name)
                     + ", error: " + str(error))
        return None


def list_of_file_handler(file_path, list_of_files):
    file_name = ''
    for file in list_of_files:
        if 'content' in file and file['content'] is not None:
            name = store_file(base64_encode_content=file['content'], file_path=file_path, file_name=file['name'])
            file_name = file_name + name + ','
        elif 'name' in file:
            file_name = file_name + file['name'] + ','
        else:
            """
            empty block
            """
            pass
    return file_name[:-1]


def create_commit_objects(project_name, user_email, date, commit_sha, git_repo, uuid, username):
    try:
        project = Project.objects.get(name=project_name)
    except Exception as error:
        LOGGER.info("Error in fetching application with name: "+str(project_name)+": "+str(error))
        return False
    try:
        if uuid:
            user = User.objects.get(name=username, uuid=uuid)
        else:
            user=User.objects.get(name=username)
    except Exception as error:
        LOGGER.info("Error in fetching user with name: "+str(user_email)+": "+str(error))
        LOGGER.info("Creating the user: "+str(user_email))
        user=User.objects.create(email=uuid, name=username, uuid=uuid)
        return False
    sha_exists = DeveloperDashboardData.objects.filter(commit_sha=commit_sha, project=project, git_repo=git_repo)
    if not sha_exists:
        print(date)
        DeveloperDashboardData.objects.create(project=project,
                                              git_repo = git_repo,
                                               user=user, date = datetime(int(date.split("-")[0]),
                                                                int(date.split("-")[1]),
                                                                int(date.split("-")[2])), 
                                                                commit_sha=commit_sha)
    return True

def create_pr_objects(project_name, author_display_id, date, uuid, state, merger_display_name, merger_uuid,git_repo, pr_id):
    uid = uuid
    print()
    try:
        project = Project.objects.get(name=project_name)
    except Exception as error:
        LOGGER.info("Error in fetching application with name: "+str(project_name)+": "+str(error))
        return False
    try:
        print(1)
        author_user = User.objects.get(name=author_display_id, uuid=uid)
    except Exception as error:
        print(2)
        LOGGER.info("Error in fetching user with name: "+str(author_display_id)+": "+str(error))
        LOGGER.info("Creating the user: "+str(author_display_id))
        author_user=User.objects.create(name=author_display_id, email = uid, uuid=uid)
    try:
        merger_user=None
        if merger_display_name and merger_uuid:
            print(3)
            print(type(merger_display_name), type(merger_uuid))
            merger_user = User.objects.get(name=merger_display_name, uuid=merger_uuid)
    except Exception as error:
        print(4)
        LOGGER.info("Error in fetching user with name: "+str(merger_display_name)+": "+str(error))
        LOGGER.info("Creating the user: "+str(merger_display_name))
        merger_user=User.objects.create(name=merger_display_name, email = merger_uuid, uuid=merger_uuid)
    print(date)
    DeveloperDashboardPRData.objects.create(project=project,
                                            git_repo = git_repo,
                                            date = datetime(int(date.split("-")[0]),
                                                            int(date.split("-")[1]),
                                                            int(date.split("-")[2])),
                                            author_user = author_user,
                                            merger_user = merger_user,
                                            state=state,
                                            pr_id=pr_id)
    return True

def create_project_git_repo_mapping(git_repo, project_names):
    for project in project_names:
        try:
            project_obj = Project.objects.get(name=project)
        except Exception as error:
            project_obj = Project.objects.create(name=project, description="Automated creation of application by system")
        if not len(ProjectGitRepoMapping.objects.filter(project=project_obj, git_repo=git_repo)):
            ProjectGitRepoMapping.objects.create(project=project_obj, git_repo=git_repo)

def trigger_task_to_generate_git_repo_data(git_repo):
    kwargs = {}
    kwargs["git_repo_id"]=git_repo.id
    kwargs["git_repo_provider_id"]=git_repo.git_provider.id
    today_date = datetime.now()
    two_years_back_date = today_date - timedelta(days=2*365)
    two_years_back_date_string = two_years_back_date.strftime("%Y-%m-%d")
    kwargs["start_date"]= two_years_back_date_string
    app.send_task("metric_api.developer_dashboard_data_generator", kwargs=kwargs)
# '''
# incoming data - {application:{user:user_data}}
# cache data - {application:{date:{user:user_data} }
# '''
# def set_developer_cache_datewise(json_data, date):
#     cache_key = "DEVELOPER_DASHBOARD"
#     dev_json = cache.get("DEVELOPER_DASHBOARD")
#     if not dev_json:
#         dev_json={}
#     print("ds",json_data)
#     for application in json_data.keys():
#         for user in json_data[application]:
#             if not application in dev_json:
#                 dev_json[application]={date:{user:{"number_of_commits": 0}}, "commit_sha":[]}
#             if not date in dev_json[application]:
#                 dev_json[application][date]={user:{"number_of_commits": 0}}
#             if not user in dev_json[application][date]:
#                 dev_json[application][date][user]={"number_of_commits": 0}
#             if json_data[application][user]["commit_sha"][0] in dev_json[application]["commit_sha"]:
#                 print("reachedd here")
#                 continue        
#             dev_json[application][date][user]["number_of_commits"] += json_data[application][user]["number_of_commits"]
#             for commit_sha in json_data[application][user]["commit_sha"]:
#                 dev_json[application]["commit_sha"].append(commit_sha)
#             # dev_json[application]["commit_sha"].append    
#     cache.set("DEVELOPER_DASHBOARD", dev_json)
# '''
# data --> app:date:user:user_data
# '''

# def create_weekly_data_on_the_basis_of_start_date_end_date(week_json, dev_json):
#     current_week_start_date = datetime.strptime(week_json["current_week"]["start_date"], "%Y-%m-%d")
#     current_week_end_date = datetime.strptime(week_json["current_week"]["end_date"], "%Y-%m-%d")
#     previous_week_start_date = datetime.strptime(week_json["previous_week"]["start_date"], "%Y-%m-%d")
#     previous_week_end_date = datetime.strptime(week_json["previous_week"]["end_date"], "%Y-%m-%d")
#     print("dates")
#     print(current_week_start_date)
#     print(current_week_end_date)
#     print(previous_week_start_date)
#     print(previous_week_end_date)
#     print("----------------------")
#     if not week_json["current_week"]["data"] and not week_json["previous_week"]["data"]:
#         week_json_data = {"current_week":{}, "previous_week":{}}
#         for application in dev_json:
#             if application == "week_data":
#                 continue
#             if application not in week_json_data["current_week"]:
#                 week_json_data["current_week"][application] = {}
#             if application not in week_json_data["previous_week"]:
#                 week_json_data["previous_week"][application] = {}
#             for date in dev_json[application]:
#                 if date=="commit_sha":
#                     continue
#                 print(date)
#                 date_obj = datetime.strptime(date, "%Y-%m-%d")
#                 #current week
#                 if date_obj <= current_week_end_date and date_obj >= current_week_start_date:
#                     print("here")
#                     week_json_data["current_week"][application][date] = dev_json[application][date]
#                 #previous week
#                 if date_obj <= previous_week_end_date and date_obj >= previous_week_start_date:
#                     print("there")
#                     week_json_data["previous_week"][application][date] = dev_json[application][date]
#         week_json["current_week"]["data"] = week_json_data["current_week"]
#         week_json["previous_week"]["data"] = week_json_data["previous_week"]
#     # else:
#     #     current_week_start_date = current_week_start_date + timedelta(days=1)
#     #     current_week_end_date = current_week_end_date + timedelta(days=1)
#     #     previous_week_start_date = previous_week_start_date + timedelta (days=1)
#     #     previous_week_end_date = previous_week_end_date + timedelta(days=1)
#     #     print("dates new")
#     #     print(current_week_start_date)
#     #     print(current_week_end_date)
#     #     print(previous_week_start_date)
#     #     print(previous_week_end_date)
#     #     print("----------------------")
#     #     for application in week_json["current_week"]["data"]:
#     #         if week_json["current_week"]["start_date"] in week_json["current_week"]["data"][application]:
#     #             week_json["current_week"]["data"][application].pop(week_json["current_week"]["start_date"])
#     #         if current_week_end_date in dev_json[application]:
#     #             week_json["current_week"]["data"][application][current_week_end_date] = dev_json[application][current_week_end_date] 

#     #         if week_json["previous_week"]["start_date"] in week_json["previous_week"]["data"][application]:
#     #             week_json["previous_week"]["data"][application].pop(week_json["previous_week"]["start_date"])
#     #         if previous_week_end_date in dev_json[application]:
#     #             week_json["previous_week"]["data"][application][current_week_end_date] = dev_json[application][previous_week_end_date]
#     #     week_json["current_week"]["start_date"] = current_week_start_date.strftime("%Y-%m-%d")
#     #     week_json["current_week"]["end_date"] = current_week_end_date.strftime("%Y-%m-%d")
#     #     week_json["previous_week"]["start_date"] = previous_week_start_date.strftime("%Y-%m-%d")
#     #     week_json["previous_week"]["end_date"] = previous_week_end_date.strftime("%Y-%m-%d")
#     dev_json["week_data"] = week_json
#     cache.set("DEVELOPER_DASHBOARD",dev_json)
# '''                 
# week data -> week_data:{"current_week":{"start_date":date, "end_date":date, data:data}},
# prev_week_data:{"start_data":data, "end_date",date, data:data}}
# '''
# def set_developer_cache_weekwise():
#     # current_date = datetime.now()-timedelta(days=1)
#     current_date = datetime.strptime("2023-05-23", "%Y-%m-%d")
#     one_week_ago = current_date - timedelta(weeks=1)
#     prev_week_start_date = one_week_ago - timedelta(weeks=1)
#     prev_week_end_date = one_week_ago-timedelta(days=1)
#     cache_key = "DEVELOPER_DASHBOARD"
#     dev_json = cache.get("DEVELOPER_DASHBOARD")
#     print(dev_json)
#     # week_json = dev_json.get("week_data",None)
#     # if not week_json:
#     week_json = {"current_week":{"start_date":one_week_ago.strftime("%Y-%m-%d"), "end_date":current_date.strftime("%Y-%m-%d"),"data":{}},
#                     "previous_week":{"start_date":prev_week_start_date.strftime("%Y-%m-%d"), "end_date":prev_week_end_date.strftime("%Y-%m-%d"),"data":{}}}
#     create_weekly_data_on_the_basis_of_start_date_end_date(week_json, dev_json)

# def get_week_of_month(month_start_date, month_end_date, date):
#     # month_start_date = datetime.strptime(month_start_date, "%Y-%m-%d")
#     # month_end_date = datetime.strptime(month_end_date, "%Y-%m-%d")
#     date = datetime.strptime(date, "%Y-%m-%d")
#     delta_days = (date - month_start_date).days
#     week_number = (delta_days // 7) + 1
#     return week_number

# def get_month_name(date_string):
#     date_object = datetime.strptime(date_string, '%Y-%m-%d')
#     month_name = date_object.strftime('%B')
#     return month_name

# def create_yearly_data_on_the_basis_of_start_date_end_date(year_json, dev_json):
#     current_year_start_date = datetime.strptime(year_json["current_year"]["start_date"], "%Y-%m-%d")
#     current_year_end_date = datetime.strptime(year_json["current_year"]["end_date"], "%Y-%m-%d")
#     previous_year_start_date = datetime.strptime(year_json["previous_year"]["start_date"], "%Y-%m-%d")
#     previous_year_end_date = datetime.strptime(year_json["previous_year"]["end_date"], "%Y-%m-%d")
#     print("dates")
#     print(current_year_start_date)
#     print(current_year_end_date)
#     print(previous_year_start_date)
#     print(previous_year_end_date)
#     print("----------------------")
#     if not year_json["current_year"]["data"] and not year_json["previous_year"]["data"]:
#         year_json_data = {"current_year":{}, "previous_year":{}}
#         for application in dev_json:
#             if application not in year_json_data["current_year"]:
#                 year_json_data["current_year"][application] = {}
#             if application not in year_json_data["previous_year"]:
#                 year_json_data["previous_year"][application] = {}
#             for date in dev_json[application]:
#                 month_name = get_month_name(date)
#                 date_obj = datetime.strptime(date, "%Y-%m-%d")
#                 #current week
#                 if date_obj <= current_year_end_date and date_obj >= current_year_start_date:
#                     print("here")
#                     if month_name not in year_json_data["current_year"][application]:
#                         year_json_data["current_year"][application][month_name] = {}
#                     for user in dev_json["current_year"][application][month_name]:
#                         year_json_data["current_year"][application][month_name][user]={}
#                         if "number_of_commits" not in year_json_data["current_year"][application][month_name][user]:
#                             year_json_data["current_year"][application][month_name][user]["number_of_commits"] = 0
#                         year_json_data["current_year"][application][month_name][user]["number_of_commits"] += dev_json[application][date][user]["number_of_commits"]
#                 if date_obj <= previous_year_end_date and date_obj >= previous_year_start_date:
#                     print("there")
#                     if month_name not in year_json_data["previous_month"][application]:
#                         year_json_data["previous_month"][application][month_name] = {}
#                     for user in dev_json["previous_month"][application][month_name]:
#                         year_json_data["previous_month"][application][month_name][user]={}
#                         if "number_of_commits" not in year_json_data["previous_month"][application][month_name][user]:
#                             year_json_data["previous_month"][application][month_name][user]["number_of_commits"] = 0
#                         year_json_data["previous_month"][application][month_name][user]["number_of_commits"] += dev_json[application][date][user]["number_of_commits"]
                
#         year_json["current_month"]["data"] = year_json_data["current_month"]
#         year_json["previous_month"]["data"] = year_json_data["previous_month"]

#     dev_json["year_data"] = year_json
#     cache.set("DEVELOPER_DASHBOARD",dev_json)

# def create_monthly_data_on_the_basis_of_start_date_end_date(month_json, dev_json):
#     current_month_start_date = datetime.strptime(month_json["current_month"]["start_date"], "%Y-%m-%d")
#     current_month_end_date = datetime.strptime(month_json["current_month"]["end_date"], "%Y-%m-%d")
#     previous_month_start_date = datetime.strptime(month_json["previous_month"]["start_date"], "%Y-%m-%d")
#     previous_month_end_date = datetime.strptime(month_json["previous_month"]["end_date"], "%Y-%m-%d")
#     print("dates")
#     print(current_month_start_date)
#     print(current_month_end_date)
#     print(previous_month_start_date)
#     print(previous_month_end_date)
#     print("----------------------")
#     if not month_json["current_month"]["data"] and not month_json["previous_month"]["data"]:
#         month_json_data = {"current_month":{}, "previous_month":{}}
#         for application in dev_json:
#             if application == "week_data" or application == "month_data":
#                 continue
#             if application not in month_json_data["current_month"]:
#                 month_json_data["current_month"][application] = {}
#             if application not in month_json_data["previous_month"]:
#                 month_json_data["previous_month"][application] = {}
#             for date in dev_json[application]:
#                 if date == "commit_sha":
#                     continue
#                 week_number = get_week_of_month(current_month_start_date, current_month_end_date, date)
#                 date_obj = datetime.strptime(date, "%Y-%m-%d")
#                 #current week
#                 if date_obj <= current_month_end_date and date_obj >= current_month_start_date:
#                     print("here")
#                     print(date)
#                     if week_number not in month_json_data["current_month"][application]:
#                         month_json_data["current_month"][application][week_number] = {}
#                     for user in dev_json[application][date]:
#                         if user not in month_json_data["current_month"][application][week_number]:
#                             month_json_data["current_month"][application][week_number][user]={}
#                         if "number_of_commits" not in month_json_data["current_month"][application][week_number][user]:
#                             month_json_data["current_month"][application][week_number][user]["number_of_commits"] = 0
#                         print(month_json_data)
#                         month_json_data["current_month"][application][week_number][user]["number_of_commits"] += dev_json[application][date][user]["number_of_commits"]
#                         print("---")
#                         print(month_json_data)
#                 if date_obj <= previous_month_end_date and date_obj >= previous_month_start_date:
#                     print("there")
#                     print(date)
#                     if week_number not in month_json_data["previous_month"][application]:
#                         month_json_data["previous_month"][application][week_number] = {}
#                     for user in dev_json[application][date]:
#                         month_json_data["previous_month"][application][week_number][user]={}
#                         if "number_of_commits" not in month_json_data["previous_month"][application][week_number][user]:
#                             month_json_data["previous_month"][application][week_number][user]["number_of_commits"] = 0
#                         month_json_data["previous_month"][application][week_number][user]["number_of_commits"] += dev_json[application][date][user]["number_of_commits"]
                
#         month_json["current_month"]["data"] = month_json_data["current_month"]
#         month_json["previous_month"]["data"] = month_json_data["previous_month"]

#     dev_json["month_data"] = month_json
#     cache.set("DEVELOPER_DASHBOARD",dev_json)

# def set_developer_cache_monthwise():
#     # current_date = datetime.now()-timedelta(days=1)
#     current_date = datetime.strptime("2023-05-23", "%Y-%m-%d")
    
#     one_month_ago = current_date - relativedelta(months=1)
#     prev_month_start_date = one_month_ago - relativedelta(months=1)
#     prev_month_end_date = one_month_ago-timedelta(days=1)
#     cache_key = "DEVELOPER_DASHBOARD"
#     dev_json = cache.get("DEVELOPER_DASHBOARD")
#     print(dev_json)
#     # month_json = dev_json.get("month_data",None)
#     # if not month_json:
#     month_json = {"current_month":{"start_date":one_month_ago.strftime("%Y-%m-%d"), "end_date":current_date.strftime("%Y-%m-%d"),"data":{}},
#                      "previous_month":{"start_date":prev_month_start_date.strftime("%Y-%m-%d"), "end_date":prev_month_end_date.strftime("%Y-%m-%d"),"data":{}}}
#     create_monthly_data_on_the_basis_of_start_date_end_date(month_json, dev_json)


# #shifted to new file
# def fetch_bitbucket_commits(base_url, workspace, repo_slug, username, app_password, start_date, repo_projects, per_page=30):
#     import os
#     import requests
#     from requests.auth import HTTPBasicAuth
#     from datetime import datetime
#     commit_json = {}
#     date_over = False
#     url = f"{base_url}/repositories/{workspace}/{repo_slug}/commits"
#     auth = HTTPBasicAuth(username, app_password)
#     params = {"pagelen": per_page}
#     all_commits = []
#     next_page = url
#     while next_page:
#         response = requests.get(next_page, auth=auth, params=params)
#         if response.status_code != 200:
#             print(f"Failed to fetch commits: {response.status_code} - {response.text}")
#             return False
#         data = response.json()
#         commits = data.get("values", [])
#         for commit in commits:
#             author_email = commit["author"]["raw"].split("<")[1].split(">")[0]
#             date = commit["date"].split("T")[0]
#             if start_date:
#                 current_date = datetime.strptime(start_date, '%Y-%m-%d')
#                 commit_date = datetime.strptime(date, '%Y-%m-%d')
#                 if commit_date<current_date:
#                     date_over=True
#                     break
#             for application in repo_projects:
#                 if not application.name in commit_json:
#                     commit_json[application.name]={}
#                 if not author_email in commit_json[application.name]:
#                     commit_json[application.name][author_email]=0
#                 commit_json[application.name][author_email]["number_of_commits"] += 1 
#             set_developer_cache_datewise(date=date, json_data=commit_json)
#             commit_json={}
#         if date_over:
#            break 
#         next_page = data.get("next", None)
        
#     return True
    
# def get_bitbucket_commit_data(start_date=None):
#     all_bitbucket_git_repo = GitRepo.objects.filter(git_provider_id=3000)
#     for git_repo in all_bitbucket_git_repo:
#         repo_projects = ApplicationServiceMapping.objects.filter(git_repo=git_repo)
#         username = git_repo.credential.username
#         app_password = git_repo.credential.password
#         base_url = "https://api.bitbucket.org/2.0"
#         relevent_part = git_repo.git_url.split('@bitbucket.org/')[1].split('.git')[0]
#         workspace, repo_slug = relevent_part.split("/")
#         commits = fetch_bitbucket_commits(base_url, workspace, repo_slug, username, app_password, start_date, repo_projects)


# def fetch_github_branches(url, headers):
#     import requests
#     from datetime import datetime
#     response = requests.get(url, headers=headers)
#     if response.status_code != 200:
#         print(f"Error: Failed to fetch branches. Status code: {response.status_code}")
#         exit()
#     branches = response.json()
#     return branches

# def get_github_commit_data(start_date=None):
#     import requests
#     from datetime import datetime
#     all_github_git_repo = GitRepo.objects.filter(git_provider_id=1000)
#     for git_repo in all_github_git_repo:
#         repo_projects = ApplicationServiceMapping.objects.filter(git_repo=git_repo)
#         access_token = git_repo.credential.password
#         repo_name = git_repo.git_url.split("github.com/")[1]
#         url = f"https://api.github.com/repos/{repo_name}/branches"
#         headers = {
#             'Authorization': f'token {access_token}',
#             'Accept': 'application/vnd.github.v3+json'
#         }
#         branches = fetch_github_branches(url=url, headers=headers)
#         commit_json={}
#         date_over=False
#         for branch in branches:
#             branch_name = branch['name']
#             branch_url = f"https://api.github.com/repos/{repo_name}/commits"
#             params = {
#                 'sha': branch_name,
#                 'per_page': 30
#             }
#             while True:
#                 branch_response = requests.get(branch_url, params=params, headers=headers)
#                 if branch_response.status_code != 200:
#                     print(f"Error: Failed to fetch commits for branch {branch_name}. Status code: {branch_response.status_code}")
#                     break
#                 branch_commits = branch_response.json()
#                 if not branch_commits:
#                     break
#                 for commit in branch_commits:
#                     author_email = commit['commit']['author']['name']
#                     date = commit['commit']['author']['date']
#                     if start_date:
#                         current_date = datetime.strptime(start_date, '%Y-%m-%d')
#                         commit_date = datetime.strptime(date, '%Y-%m-%d')
#                         if commit_date<current_date:
#                             date_over=True
#                             break
#                     for application in repo_projects:
#                         if not application.name in commit_json:
#                             commit_json[application.name]={}
#                         if not author_email in commit_json[application.name]:
#                             commit_json[application.name][author_email]=0
#                         commit_json[application.name][author_email]["number_of_commits"] += 1 
#                     set_developer_cache_datewise(date=date, json_data=commit_json)
#                     commit_json={}
#                 if date_over:
#                    break 
        
#                 # Move to the next page
#                 if 'next' in branch_response.links:
#                     branch_url = branch_response.links['next']['url']
#                 else:
#                     break

        
# def get_all_commits(project, branch_name, start_date, repo_projects):
#     commit_json = []
#     page = 1
#     per_page = 30
#     while True:
#         page_commits = project.commits.list(ref_name=branch_name, since=start_date, page=page, per_page=per_page)
#         if not page_commits:
#             break
#         for commit in page_commits:
#             author_email = commit.author_email
#             date = commit.committed_date
#             for application in repo_projects:
#                 if not application.name in commit_json:
#                     commit_json[application.name]={}
#                 if not author_email in commit_json[application.name]:
#                     commit_json[application.name][author_email]=0
#                 commit_json[application.name][author_email]["number_of_commits"] += 1 
#             set_developer_cache_datewise(date=date, json_data=commit_json)
#             commit_json={}
#         page += 1
#     return True

# def get_gitlab_commit_data(start_date=None):
#     import gitlab
#     from datetime import datetime
#     all_github_git_repo = GitRepo.objects.filter(git_provider_id=2000)
#     for git_repo in all_github_git_repo:
#         repo_projects = ApplicationServiceMapping.objects.filter(git_repo=git_repo)
#         api_token = git_repo.credential.password
#         repository_path = git_repo.git_url.split("gitlab.com/")[1]
#         gl = gitlab.Gitlab('https://gitlab.com', private_token=api_token)
#         project = gl.projects.get(repository_path)
#         branches = project.branches.list(all=True)
#         for branch in branches:
#             branch_name = branch.name
#             commits = get_all_commits(branch_name, start_date=start_date, repo_projects=repo_projects)
            
            
    
       
def get_rating_evaluation_in_human(metric_index,metal_rating_evaluation_rating,type,period=None):
    rating_dict={}

    for rating in metal_rating_evaluation_rating:
        if type=='INT':
            metal_rating={}
            if rating['period']:
            
                if rating['value']!=None:
                    scaled_value=round(rating['value'],2)
                    metal_rating[rating['metal_rating']['name']]=f"{metric_index} {scaled_value} Per  {period.title()}"
                else:
                    scaled_upper_limit=round(rating['upper_limit'],2)
                    scaled_lower_limit=round(rating['lower_limit'],2)
                    metal_rating[rating['metal_rating']['name']]=f"{metric_index} between {scaled_lower_limit} - {scaled_upper_limit} Per {period.title()} "
            else:
                if rating['value']!=None:
                    if isinstance(rating['value'],str):
                        rating['value']=float(rating['value'])
                    scaled_value=round(rating['value'],2)
                    metal_rating[rating['metal_rating']['name']]=f"{metric_index} value is {' '.join(rating['operator']['name'].split('_')).title()} {scaled_value} "
                else:
                    if isinstance(rating['upper_limit'],str):
                        rating['upper_limit']=float(rating['upper_limit'])
                    if isinstance(rating['lower_limit'],str):
                        rating['lower_limit']=round(rating['lower_limit'],2)
                    scaled_upper_limit=round(rating['upper_limit'],2)
                    scaled_lower_limit=round(rating['lower_limit'],2)
                    metal_rating[rating['metal_rating']['name']]=f" {metric_index} value between {scaled_lower_limit} - {scaled_upper_limit} "
            rating_dict.update(metal_rating)
        elif type =='PERCENTAGE':
            metal_rating={}
            if rating['value']!=None:
                if rating['operator']['name'] in ('LESS_THAN','LESS_THAN_EQUAL_TO'):
                    metal_rating[rating['metal_rating']['name']]=f"0% - {rating['value']}%"
                else:
                    metal_rating[rating['metal_rating']['name']]=f"{rating['value']}% - 100%"
            else:
                metal_rating[rating['metal_rating']['name']]=f"{rating['lower_limit']}% -{rating['upper_limit']}%"
            rating_dict.update(metal_rating)
        elif type=='TIME':
            metal_rating={}
            if rating['value'] !=None:
                days,hours=get_days_hours_with_minutes(rating['value'])
                if rating['metal_rating']['name']=='ELITE':
                    metal_rating[rating['metal_rating']['name']]=f"Less Than {days} days , {math.ceil(hours)} Hours"
                if rating['metal_rating']['name']=='LOW':
                    metal_rating[rating['metal_rating']['name']]=f"Greater Than {days} days , {math.ceil(hours)} Hours"
            else:
                upper_limit_days,upper_limit_hours=get_days_hours_with_minutes(rating['upper_limit'])
                lower_limit_days,lower_limit_hours=get_days_hours_with_minutes(rating['lower_limit'])
                metal_rating[rating['metal_rating']['name']]=f"Between {upper_limit_days} days ,{math.ceil(upper_limit_hours)} hrs and {lower_limit_days} days, {math.ceil(lower_limit_hours)} hrs"
            rating_dict.update(metal_rating)

    return rating_dict

import requests
from requests.auth import HTTPBasicAuth

def update_pending_bitbucket_pr():
    all_open_pr = DeveloperDashboardPRData.objects.filter(git_repo__git_provider_id = 3000, state="OPEN")
    for open_pr in all_open_pr:
        bitbucket_token = open_pr.git_repo.credential.password
        username = open_pr.git_repo.credential.username
        auth = HTTPBasicAuth(username, bitbucket_token)
        relevent_part = open_pr.git_repo.git_url.split('bitbucket.org/')[1]
        workspace, repo_slug = relevent_part.split("/")
        url = f"https://api.bitbucket.org/2.0/repositories/{workspace}/{repo_slug}/pullrequests/{open_pr.pr_id}"
        response = requests.get(url, auth=auth)
        if response.status_code == 200:
            pr_data = response.json()
            if pr_data.get("state") == "MERGED":
                merged_by_uuid = pr_data["closed_by"]["uuid"]
                merged_by_display_name = pr_data["closed_by"]["display_name"]
                try:
                    merger_user = User.objects.get(name=merged_by_display_name, uuid=merged_by_uuid)
                except Exception as error:
                    print(4)
                    LOGGER.info("Error in fetching user with name: "+str(merged_by_display_name)+": "+str(error))
                    LOGGER.info("Creating the user: "+str(merged_by_display_name))
                    merger_user=User.objects.create(name=merged_by_display_name, email = merged_by_uuid, uuid=merged_by_uuid)
                open_pr.state = "MERGED"
                open_pr.merger_user = merger_user
                open_pr.save()

def update_pending_bitbucket_self_hosted_pr():
    all_open_pr = DeveloperDashboardPRData.objects.filter(git_repo__git_provider_id=3000, state="OPEN")
    for open_pr in all_open_pr:
        bitbucket_token = open_pr.git_repo.credential.password
        username = open_pr.git_repo.credential.username
        auth = HTTPBasicAuth(username, bitbucket_token)
        parts = open_pr.git_repo.git_url.split('/')
        project_index = parts.index('scm')
        project_key = parts[project_index + 1]
        repo_name = parts[project_index + 2]
        url = f"{parts[2]}/bitbucket/rest/api/latest/projects/{project_key}/repos/{repo_name}/pull-requests/{open_pr.pr_id}/activities"
        response = requests.get(url, auth=auth)
        if response.status_code == 200:
            pr_data = response.json()
            pr_data = pr_data.get("values",[])
            for i in pr_data:
                if i["action"] == "MERGED":
                    user_name1=None
                    if 'emailAddress' not in  i["user"]:
                        user_name1=i["user"]['displayName']
                    else:
                        user_name1=i["user"]['emailAddress'].split("@")[0]
                    merged_by_uuid = user_name1
                    merged_by_display_name = user_name1
                    try:
                        merger_user = User.objects.get(name=merged_by_display_name, uuid=merged_by_uuid)
                    except Exception as error:
                        print(4)
                        LOGGER.info("Error in fetching user with name: "+str(merged_by_display_name)+": "+str(error))
                        LOGGER.info("Creating the user: "+str(merged_by_display_name))
                        merger_user=User.objects.create(name=merged_by_display_name, email = merged_by_uuid, uuid=merged_by_uuid)
                    open_pr.state = "MERGED"
                    open_pr.merger_user = merger_user
                    open_pr.save()
                    break




def update_pending_gitlab_pr():
    all_open_mr = DeveloperDashboardPRData.objects.filter(git_repo__git_provider_id=2000, state="opened")
    
    for open_mr in all_open_mr:
        gitlab_token = open_mr.git_repo.credential.password
        # Note: GitLab uses tokens directly in headers for authentication
        headers = {
        "Private-Token": gitlab_token
        }
        base_url = "https://gitlab.com/api/v4"
        # Extract project path and encode it
        project_path = open_mr.git_repo.git_url.split('gitlab.com/')[1].replace('.git', '')
        encoded_project_path = requests.utils.quote(project_path, safe='')
        # Get project ID from URL
        project_url = f"{base_url}/projects/{encoded_project_path}"
        response = requests.get(project_url, headers=headers)
        if response.status_code != 200:
            print(f"Failed to fetch project ID: {response.status_code} - {response.text}")
            break
        project_id = response.json()['id']
        url = f"{base_url}/projects/{project_id}/merge_requests/{open_mr.pr_id}"
        
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            mr_data = response.json()
            if mr_data.get("state") == "merged":
                merged_by_id = mr_data["merged_by"]["id"]
                merged_by_name = mr_data["merged_by"]["name"]
                try:
                    merger_user = User.objects.get(name=merged_by_name, uuid=merged_by_id)
                except Exception as error:
                    LOGGER.info("Error in fetching user with name: " + str(merged_by_name) + ": " + str(error))
                    LOGGER.info("Creating the user: " + str(merged_by_name))
                    merger_user = User.objects.create(
                        name=merged_by_name,
                        email=merged_by_id,
                        uuid=merged_by_id
                    )
                
                # Update the MR state and merger details
                open_mr.state = "merged"
                open_mr.merger_user = merger_user
                open_mr.save()
        else:
            LOGGER.error(f"Failed to fetch MR data for MR ID {open_mr.pr_id}. Status code: {response.status_code}")

    
def update_pending_github_pr():
    all_open_pr = DeveloperDashboardPRData.objects.filter(git_repo__git_provider_id=1000, state="open")
    
    for open_pr in all_open_pr:
        github_token = open_pr.git_repo.credential.password
        headers = {
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        # Parse owner and repo name from the GitHub repository URL
        relevant_part = open_pr.git_repo.git_url.split('github.com/')[1]
        owner, repo = relevant_part.split("/")
        
        # Use GitHub's API to get PR details by PR ID (number)
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{open_pr.pr_id}"
        
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            pr_data = response.json()
            if pr_data.get("merged") == True:
                merged_by_login = pr_data["merged_by"]["login"]
                merged_by_id = pr_data["merged_by"]["id"]
                
                try:
                    merger_user = User.objects.get(name=merged_by_login, uuid=merged_by_id)
                except Exception as error:
                    merger_user = User.objects.create(
                        name=merged_by_login,
                        email=merged_by_id,
                        uuid=merged_by_id
                    )
                open_pr.state = "closed"
                open_pr.merger_user = merger_user
                open_pr.save()
