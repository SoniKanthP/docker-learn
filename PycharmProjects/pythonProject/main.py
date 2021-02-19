####################################################################################
# Version: 1.0
# Author: Soni Kanth Potlapelli
# Description: Access Key Rotation
# Date: 9th Feb 2021

#/Users/sonikanth/PycharmProjects/pythonProject/main.py
####################################################################################


import boto3, sys, datetime, time, json
import botocore
from datetime import datetime, timezone
from botocore.exceptions import ClientError

iam = boto3.client('iam')
secretmanager = boto3.client('secretsmanager')
sns_client = boto3.client('sns')
access_key = []
user = "admin"
env = "dev"

def get_current_access_key(iam_user_name):
    try:
        # List access keys through the pagination interface.
        paginator = iam.get_paginator('list_access_keys')
        # response = paginator.paginate(UserName=iam_user_name):
        for response in paginator.paginate(UserName=iam_user_name):
            access_key_1 = (response['AccessKeyMetadata'][0])
            access_key_2 = (response['AccessKeyMetadata'][1])

            access_keyID_1 = (response['AccessKeyMetadata'][0]['AccessKeyId'])
            access_keyID_2 = (response['AccessKeyMetadata'][1]['AccessKeyId'])

            create_date_1 = time.mktime(response['AccessKeyMetadata'][0]['CreateDate'].timetuple())
            now = time.time()
            age1 = (now - create_date_1) // 86400

            create_date_2 = time.mktime(response['AccessKeyMetadata'][1]['CreateDate'].timetuple())
            now = time.time()
            age2 = (now - create_date_2) // 86400


            if age1 > age2:
                access_key_status = response['AccessKeyMetadata'][0]['Status']
                if (access_key_status == "Active"):
                    print("Access Key status {} is Active".format(access_keyID_1))
                    print("Access Key {} need to deactive and delete".format(access_keyID_1))
                    disable_key(access_keyID_1, iam_user_name)
                    delete_inactive_access_key(iam_user_name)
                    create_access_key(iam_user_name)
                else:
                    print("Deleting Inactive Access Key")
                    delete_inactive_access_key(iam_user_name)
                    create_access_key(iam_user_name)

            else:
                access_key_status = response['AccessKeyMetadata'][1]['Status']
                if (access_key_status == "Active"):
                    print("Access Key status {} is Active".format(access_keyID_2))
                    print("Access Key {} need to deactive and delete".format(access_keyID_2))
                    disable_key(access_keyID_2, iam_user_name)
                    delete_inactive_access_key(iam_user_name)
                    create_access_key(iam_user_name)
                else:
                    print("Deleting Inactive Access Key")
                    delete_inactive_access_key(iam_user_name)
                    create_access_key(iam_user_name)

    except botocore.exceptions.ClientError as error:
        print(error)

def num_keys(user):
    # See if IAM user already has more than one key
    paginator = iam.get_paginator('list_access_keys')
    try:
        for response in paginator.paginate(UserName=user):
            return len(response['AccessKeyMetadata'])
    except ClientError as e:
        if e.response['Error']['Code'] == 'ParamValidationError':
            raise

def create_access_key(user):
    print("UserName =", user)
    secretName = user
    response = iam.create_access_key(UserName=user)
    access_key = response['AccessKey']['AccessKeyId']
    secret_key = response['AccessKey']['SecretAccessKey']
    json_data = json.dumps(
        {'AccessKey': access_key,
         'SecretKey': secret_key})
    try:
        response = secretmanager.describe_secret(SecretId=secretName)
        secretmanager.put_secret_value(SecretId=user, SecretString=json_data)
    
    except ClientError as e:
        if e.response['Error']['Code'] == 'ResourceNotFoundException':
            print("The requested secret " + secretName + " was not found")
            print("Creating new secret with entry " + secretName)
            secretmanager.create_secret(Name=secretName, Description='Auto-created secret', SecretString=json_data)

def disable_key(access_key, username):
    try:
        iam.update_access_key(UserName=username, AccessKeyId=access_key, Status="Inactive")
        print(access_key + " has been disabled.")
    
    except ClientError as e:
        print("The access key with id %s cannot be found" % access_key)

def delete_inactive_access_key(user):
    try:
        for access_key in iam.list_access_keys(UserName=user)['AccessKeyMetadata']:
            if access_key['Status'] == 'Inactive':
                # Delete the access key.
                print('Deleting access key {0}'.format(access_key['AccessKeyId']))
                response = iam.delete_access_key(
                    UserName=user,
                    AccessKeyId=access_key['AccessKeyId']
                )
    except botocore.exceptions.ClientError as error:
        print(error)

def check_access_key_age(iam_user_name):
    try:
        keydetails = iam.list_access_keys(UserName=iam_user_name)

        for keys in keydetails['AccessKeyMetadata']:
            if (keys['Status'] == 'Active'):
                key_age = time_diff(keys['CreateDate'])
                return key_age
    except botocore.exceptions.ClientError as error:
        print(error)

def time_diff(keycreatedtime):
    now = datetime.now(timezone.utc)
    diff = now - keycreatedtime
    return diff.days

def send_remainder_email(user, AccessKey):
    user_name = user
    AccessKey = AccessKey

    sns_arn = "arn:aws:sns:ap-south-1:429495644275:test_topic_new_email"

    message = f"A new AWS IAM Access Key pair was created. Please access your secret named: {user} to retrieve the new Access Keys: {AccessKey} and update your applications accordingly.\n\n"
    message += "UserName: " + str(user) + "\n"
    message += "\n\n"
    message += "This notification was generated by the AWS Lambda Function. "

    try:
        response = sns_client.publish(
            TopicArn=sns_arn,
            Message=message,
            Subject="Gentle Remainder :: New AWS IAM Access Key Pair Not Used"
        )

    except ClientError as error:
        print(error)

def send_final_reminder_email(user, AccessKey):
    user_name = user
    AccessKey = AccessKey

    sns_arn = "arn:aws:sns:ap-south-1:429495644275:test_topic_new_email"

    message = f"A new AWS IAM Access Key pair was created. Please access your secret named: {user} to retrieve the new Access Keys: {AccessKey} and update your applications accordingly.\n\n"
    message += "UserName: " + str(user) + "\n"
    message += "\n\n"
    message += "This notification was generated by the AWS Lambda Function. "

    try:
        response = sns_client.publish(
            TopicArn=sns_arn,
            Message=message,
            Subject="Final Remainder :: New AWS IAM Access Key Pair Not Used"
        )

    except ClientError as error:
        print(error)

def send_email(user):
    user_name = user
 #   AccessKey = AccessKey
    sns_arn = "arn:aws:sns:ap-south-1:429495644275:test_topic_new_email"
    
    message = f"A new AWS IAM Access Key pair was created. Please access your secret named: {user} to retrieve the new Access Keys and update your applications accordingly.\n\n"
    message += "UserName: " + str(user) + "\n"
    message += "\n\n"
    message += "This notification was generated by the AWS Lambda Function. "

    try:
        response = sns_client.publish(
            TopicArn=sns_arn,
            Message=message,
            Subject="New AWS IAM Access Key Pair Created"
        )

    except ClientError as error:
        print(error)

def list_secret_value(user):
    secret_name = user
    region_name = "ap-south-1"
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )
    try:
        get_secret_value_response = client.get_secret_value(SecretId=secret_name)

    except ClientError as e:
        if e.response['Error']['Code'] == 'DecryptionFailureException':
            raise e
        elif e.response['Error']['Code'] == 'InternalServiceErrorException':
            raise e
        elif e.response['Error']['Code'] == 'InvalidParameterException':
            raise e
        elif e.response['Error']['Code'] == 'InvalidRequestException':
            raise e
        elif e.response['Error']['Code'] == 'ResourceNotFoundException':
            raise e

    else:
        if 'SecretString' in get_secret_value_response:
            secret = json.loads(get_secret_value_response['SecretString'])

        else:
            decoded_binary_secret = base64.b64decode(get_secret_value_response['SecretBinary'])

    return secret['AccessKey']

def last_used_response(user, accesskey):
    username = user
    ak = accesskey
    last_used_response = iam.get_access_key_last_used(AccessKeyId=ak)
    if 'LastUsedDate' not in last_used_response['AccessKeyLastUsed']:
        print("Access Key {} has been not used".format(ak))
        return True
    else:
        return False

def old_key(user):
    try:
        paginator = iam.get_paginator('list_access_keys')
        for response in paginator.paginate(UserName=user):
            create_date_1 = time.mktime(response['AccessKeyMetadata'][0]['CreateDate'].timetuple())
            create_date_2 = time.mktime(response['AccessKeyMetadata'][1]['CreateDate'].timetuple())
            
            now = time.time()
            age1 = (now - create_date_1) // 86400
            age2 = (now - create_date_2) // 86400
            
            if age1 > age2:
                return response['AccessKeyMetadata'][0]['AccessKeyId']
            else:
                return response['AccessKeyMetadata'][1]['AccessKeyId']

    except botocore.exceptions.ClientError as error:
        print(error)

def key_created_date_validation(user):
    iam_user_name = user
    paginator = iam.get_paginator('list_access_keys')
    now = time.time()

    for response in paginator.paginate(UserName=iam_user_name):
        create_date_1 = time.mktime(response['AccessKeyMetadata'][0]['CreateDate'].timetuple())
        key_age1 = (now - create_date_1) // 86400

        create_date_2 = time.mktime(response['AccessKeyMetadata'][1]['CreateDate'].timetuple())
        key_age2 = (now - create_date_2) // 86400
        
        if key_age1 or key_age2 <= 1:
            return True
        else:
            return False

def lambda_handler(event, context):

    keyage = check_access_key_age(user)
   
    if keyage < 50:
        return

    elif keyage == 50:
        num_keys(user)
        if num_keys(user) == 2:
            print("User: " + user + " in account: " + env + " has this many keys: ", num_keys(user))
            '''
                Check if both the keys are active
                if any of the key is inactive - delete the key 
                else find the old key and deactivate and delete the key
                Also check if any new keys created less than 1 day. 
            '''
            key_created_response = key_created_date_validation(user)
            if key_created_response == True:
                return
            else:
                get_current_access_key(user)  
        else:
            print("User " + user + " in account: " + env + " has this many keys: ", num_keys(user))
            create_access_key(user)
            send_email(user)

    elif keyage > 52 and keyage <=57:
        access_key = list_secret_value(user)
        print("Access Key between Age 22 and 23 is = ", access_key)
        value = last_used_response(user, access_key)
        if value == True:
            send_remainder_email(user, access_key)
        else:
            return

    elif keyage == 58:
        access_key = list_secret_value(user)
        value = last_used_response(user, access_key)
        if value == True:
            send_final_reminder_email(user, access_key)
        else:
            return

    elif keyage == 59:
        '''
            Deactivate old access key.
        '''
        old_access_key = old_key(user)
        disable_key(old_access_key, user)

    else:
        return
#EOF