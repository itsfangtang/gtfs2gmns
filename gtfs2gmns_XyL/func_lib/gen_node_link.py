# -*- coding:utf-8 -*-
##############################################################
# Created Date: Tuesday, September 19th 2023
# Contact Info: luoxiangyong01@gmail.com
# Author/Copyright: Mr. Xiangyong Luo
##############################################################

from pyufunc import func_running_time
import pandas as pd
import time
import numpy as np

from gtfs2gmns.func_lib.data_convert import (allowed_use_function,
                                             allowed_use_transferring,
                                             calculate_distance_from_geometry,
                                             convert_route_type_to_link_type,
                                             convert_route_type_to_node_type_p,
                                             convert_route_type_to_node_type_s, transferring_penalty)


@func_running_time
def create_nodes(directed_trip_route_stop_time_df: pd.DataFrame, agency_num: int = 1) -> pd.DataFrame:

    print("Info: start creating physical nodes...")

    """create physical (station) node..."""
    physical_node_df = pd.DataFrame()
    temp_df = directed_trip_route_stop_time_df.drop_duplicates(subset=['stop_id'])
    physical_node_df['name'] = temp_df['stop_id']
    physical_node_df = physical_node_df.sort_values(by=['name'])
    physical_node_df['node_id'] = np.linspace(start=1, stop=len(physical_node_df),
                                              num=len(physical_node_df)).astype('int32')
    physical_node_df['node_id'] += int(f'{agency_num}000000')
    physical_node_df['physical_node_id'] = physical_node_df['node_id']
    physical_node_df['x_coord'] = temp_df['stop_lon'].astype(float)
    physical_node_df['y_coord'] = temp_df['stop_lat'].astype(float)
    physical_node_df['route_type'] = temp_df['route_type']
    physical_node_df['route_id'] = temp_df['route_id']
    physical_node_df['node_type'] = physical_node_df.apply(
        lambda x: convert_route_type_to_node_type_p(x.route_type), axis=1)
    physical_node_df['directed_route_id'] = ""
    physical_node_df['directed_service_id'] = ""
    physical_node_df['zone_id'] = ""
    physical_node_df['agency_name'] = temp_df['agency_name']
    physical_node_df['geometry'] = 'POINT (' + physical_node_df['x_coord'].astype(str) + \
        ' ' + physical_node_df['y_coord'].astype(str) + ')'
    stop_name_id_dict = dict(zip(physical_node_df['name'], physical_node_df['node_id']))
    physical_node_df['terminal_flag'] = temp_df['terminal_flag']
    physical_node_df['ctrl_type'] = ""
    physical_node_df['agent_type'] = ""

    print("Info: start creating service nodes... \n")
    """ create service node..."""
    service_node_df = pd.DataFrame()
    temp_df = directed_trip_route_stop_time_df.drop_duplicates(subset=['directed_service_stop_id'])
    # 2.2.2 route stop node
    service_node_df['name'] = temp_df['directed_service_stop_id']
    service_node_df = service_node_df.sort_values(by=['name'])
    service_node_df['node_id'] = np.linspace(start=1, stop=len(service_node_df),
                                             num=len(service_node_df)).astype('int32')
    service_node_df['physical_node_id'] = temp_df.apply(
        lambda x: stop_name_id_dict[x.stop_id], axis=1)
    service_node_df['node_id'] += int(f'{agency_num}500000')

    service_node_df['x_coord'] = temp_df['stop_lon'].astype(
        float) - 0.000100
    service_node_df['y_coord'] = temp_df['stop_lat'].astype(
        float) - 0.000100
    service_node_df['route_type'] = temp_df['route_type']
    service_node_df['route_id'] = temp_df['route_id']
    service_node_df['node_type'] = service_node_df.apply(
        lambda x: convert_route_type_to_node_type_s(x.route_type), axis=1)
    # node_csv['terminal_flag'] = ' '
    service_node_df['directed_route_id'] = temp_df['directed_route_id'].astype(str)
    service_node_df['directed_service_id'] = temp_df['directed_service_id'].astype(str)
    service_node_df['zone_id'] = ""
    service_node_df['agency_name'] = temp_df['agency_name']
    service_node_df['geometry'] = 'POINT (' + service_node_df['x_coord'].astype(str) + \
        ' ' + service_node_df['y_coord'].astype(str) + ')'

    service_node_df['terminal_flag'] = temp_df['terminal_flag']
    service_node_df['ctrl_type'] = ""
    service_node_df['agent_type'] = ""

    print("Info: finished creating nodes...")
    return pd.concat([physical_node_df, service_node_df])


@func_running_time
def create_service_boarding_links(directed_trip_route_stop_time_df: pd.DataFrame,
                                  node_df: pd.DataFrame,
                                  one_agency_link_list: list,
                                  period_start_time: str,
                                  period_end_time: str,
                                  agency_num: int = 1) -> list:

    # initialize dictionaries
    node_id_dict = dict(zip(node_df['name'], node_df['node_id']))
    directed_service_dict = dict(zip(node_df['node_id'], node_df['name']))
    node_lon_dict = dict(zip(node_df['node_id'], node_df['x_coord']))
    node_lat_dict = dict(zip(node_df['node_id'], node_df['y_coord']))
    frequency_dict = {}

    print("Info: 1. start creating route links...")
    # generate service links
    number_of_route_links = 0
    iteration_group = directed_trip_route_stop_time_df.groupby('directed_service_id')
    labeled_directed_service_list = []

    time_start = time.time()
    for directed_service_id, route_df in iteration_group:
        if directed_service_id in labeled_directed_service_list:
            continue
        else:
            labeled_directed_service_list.append(directed_service_id)
            number_of_trips = len(route_df.trip_id.unique())
            # note the frequency of routes
            frequency_dict[directed_service_id] = number_of_trips
            one_line_df = route_df[route_df.trip_id == route_df.trip_id.unique()[0]]
            one_line_df = one_line_df.sort_values(by=['stop_sequence'])
            number_of_records = len(one_line_df)
            one_line_df = one_line_df.reset_index()

            for k in range(number_of_records - 1):
                link_id = 1000000 * agency_num + number_of_route_links + 1
                from_node_id = node_id_dict[one_line_df.iloc[k].directed_service_stop_id]
                to_node_id = node_id_dict[one_line_df.iloc[k + 1].directed_service_stop_id]
                facility_type = convert_route_type_to_link_type(one_line_df.iloc[k].route_type)
                dir_flag = 1
                directed_route_id = one_line_df.iloc[k].directed_route_id
                link_type = 1
                link_type_name = 'service_links'
                from_node_lon = float(one_line_df.iloc[k].stop_lon)
                from_node_lat = float(one_line_df.iloc[k].stop_lat)
                to_node_lon = float(one_line_df.iloc[k + 1].stop_lon)
                to_node_lat = float(one_line_df.iloc[k + 1].stop_lat)
                length = calculate_distance_from_geometry(
                    from_node_lon, from_node_lat, to_node_lon, to_node_lat)
                lanes = number_of_trips
                capacity = 999999
                VDF_fftt1 = one_line_df.iloc[k + 1].arrival_time - one_line_df.iloc[k].arrival_time
                # minutes
                VDF_cap1 = lanes * capacity
                free_speed = ((length / 1000) / (VDF_fftt1.seconds / 3600 + 0.001)) * 60
                # (kilometers/minutes)*60 = kilometer/hour
                VDF_alpha1 = 0.15
                VDF_beta1 = 4
                VDF_penalty1 = 0
                cost = 0
                geometry = 'LINESTRING (' + str(from_node_lon) + ' ' + str(from_node_lat) + ', ' + \
                    str(to_node_lon) + ' ' + str(to_node_lat) + ')'
                agency_name = one_line_df.agency_name[0]
                allowed_use = allowed_use_function(one_line_df.iloc[k].route_type)
                stop_sequence = one_line_df.iloc[k].stop_sequence
                directed_service_id = one_line_df.iloc[k].directed_service_id
                link_list = [link_id, from_node_id, to_node_id, facility_type, dir_flag, directed_route_id,
                             link_type, link_type_name, length, lanes, capacity, free_speed, cost,
                             VDF_fftt1, VDF_cap1, VDF_alpha1, VDF_beta1, VDF_penalty1, geometry, allowed_use,
                             agency_name,
                             stop_sequence, directed_service_id]
                one_agency_link_list.append(link_list)
                number_of_route_links += 1
                if number_of_route_links % 100 == 0:
                    time_end = time.time()
                    print('convert ', number_of_route_links,
                          'service links successfully...', 'using time', time_end - time_start, 's')

    print("2. start creating boarding links from stations to their passing routes...")
    """boarding_links"""
    service_node_df = node_df[node_df.node_id != node_df.physical_node_id]
    #  select service node from node_df
    service_node_df = service_node_df.reset_index()
    number_of_sta2route_links = 0
    for iter, row in service_node_df.iterrows():
        link_id = agency_num * 1000000 + number_of_route_links + number_of_sta2route_links
        from_node_id = row.physical_node_id
        to_node_id = row.node_id
        facility_type = convert_route_type_to_link_type(row.route_type)
        dir_flag = 1
        directed_route_id = row.directed_route_id
        link_type = 2
        link_type_name = 'boarding_links'
        to_node_lon = row.x_coord
        to_node_lat = row.y_coord
        from_node_lon = node_lon_dict[row.physical_node_id]
        from_node_lat = node_lat_dict[row.physical_node_id]
        length = calculate_distance_from_geometry(
            from_node_lon, from_node_lat, to_node_lon, to_node_lat)
        free_speed = 2
        lanes = 1
        capacity = 999999
        VDF_cap1 = lanes * capacity
        VDF_alpha1 = 0.15
        VDF_beta1 = 4
        VDF_penalty1 = 0
        cost = 0
        stop_sequence = -1
        directed_service_id = directed_service_dict[to_node_id]
        geometry = 'LINESTRING (' + str(from_node_lon) + ' ' + str(from_node_lat) + ', ' + \
            str(to_node_lon) + ' ' + str(to_node_lat) + ')'
        agency_name = row.agency_name
        allowed_use = allowed_use_function(row.route_type)

        # inbound links (boarding)

        VDF_fftt1 = 0.5 * ((period_end_time - period_start_time) / frequency_dict[row.directed_service_id])
        VDF_fftt1 = min(VDF_fftt1.seconds / 60, 10)
        # waiting time at a station is 10 minutes at most
        geometry = 'LINESTRING (' + str(to_node_lon) + ' ' + str(to_node_lat) + ', ' + \
            str(from_node_lon) + ' ' + str(from_node_lat) + ')'
        # inbound link is average waiting time derived from frequency
        link_list_inbound = [link_id, from_node_id, to_node_id, facility_type, dir_flag, directed_route_id,
                             link_type, link_type_name, length, lanes, capacity, free_speed, cost,
                             VDF_fftt1, VDF_cap1, VDF_alpha1, VDF_beta1, VDF_penalty1, geometry, allowed_use,
                             agency_name,
                             stop_sequence, directed_service_id]
        number_of_sta2route_links += 1

        # outbound links (boarding)
        link_id = agency_num * 1000000 + number_of_route_links + number_of_sta2route_links
        VDF_fftt1 = 1  # (length / free_speed) * 60
        #  the time of outbound time
        link_list_outbound = [link_id, to_node_id, from_node_id, facility_type, dir_flag, directed_route_id,
                              link_type, link_type_name, length, lanes, capacity, free_speed, cost,
                              VDF_fftt1, VDF_cap1, VDF_alpha1, VDF_beta1, VDF_penalty1, geometry, allowed_use,
                              agency_name,
                              stop_sequence, directed_service_id]
        one_agency_link_list.append(link_list_inbound)
        one_agency_link_list.append(link_list_outbound)
        number_of_sta2route_links += 1
        #  one inbound link and one outbound link
        if number_of_sta2route_links % 100 == 0:
            time_end = time.time()
            print('convert ', number_of_sta2route_links,
                  'boarding links successfully...', 'using time', time_end - time_start, 's')

    return one_agency_link_list


@func_running_time
def create_transferring_links(all_node_df: pd.DataFrame, all_link_list: list) -> list:

    physical_node_df = all_node_df[all_node_df.node_id ==
                                   all_node_df.physical_node_id]
    physical_node_df = physical_node_df.reset_index()
    number_of_transferring_links = 0
    time_start = time.time()

    for i in range(len(physical_node_df)):
        ref_x = physical_node_df.iloc[i].x_coord
        ref_y = physical_node_df.iloc[i].y_coord

        mask1 = physical_node_df.x_coord >= (ref_x - 0.003)
        mask2 = physical_node_df.x_coord <= (ref_x + 0.003)
        mask3 = physical_node_df.y_coord >= (ref_y - 0.003)
        mask4 = physical_node_df.y_coord <= (ref_y + 0.003)

        neighboring_node_df = physical_node_df[mask1 & mask2 & mask3 & mask4]

        # neighboring_node_df = physical_node_df[(physical_node_df.x_coord >= (ref_x - 0.003)) &
        #                                        (physical_node_df.x_coord <= (ref_x + 0.003))]
        # neighboring_node_df = neighboring_node_df[(neighboring_node_df.y_coord >= (ref_y - 0.003)) &
        #                                           (neighboring_node_df.y_coord <= (ref_y + 0.003))]

        labeled_list = []
        count = 0
        for j in range(len(neighboring_node_df)):
            if count >= 10:
                break
            if (physical_node_df.iloc[i].route_id, physical_node_df.iloc[i].agency_name) == \
                    (neighboring_node_df.iloc[j].route_id, neighboring_node_df.iloc[j].agency_name):
                continue
            from_node_lon = float(physical_node_df.iloc[i].x_coord)
            from_node_lat = float(physical_node_df.iloc[i].y_coord)
            to_node_lon = float(neighboring_node_df.iloc[j].x_coord)
            to_node_lat = float(neighboring_node_df.iloc[j].y_coord)
            length = calculate_distance_from_geometry(
                from_node_lon, from_node_lat, to_node_lon, to_node_lat)
            if (length > 321.869) | (length < 1):
                continue
            if (neighboring_node_df.iloc[j].route_id, neighboring_node_df.iloc[j].agency_name) in labeled_list:
                continue
            count += 1
            labeled_list.append(
                (neighboring_node_df.iloc[j].route_id, neighboring_node_df.iloc[j].agency_name))
            # consider only one stops of another route
            # transferring 1
            #  print('transferring link length =', length)
            link_id = number_of_transferring_links + 1
            from_node_id = physical_node_df.iloc[i].node_id
            to_node_id = neighboring_node_df.iloc[j].node_id
            facility_type = 'sta2sta'
            dir_flag = 1
            directed_route_id = -1
            link_type = 3
            link_type_name = 'transferring_links'
            lanes = 1
            capacity = 999999
            VDF_fftt1 = (length / 1000) / 1
            VDF_cap1 = lanes * capacity
            free_speed = 1
            # 1 kilo/hour
            VDF_alpha1 = 0.15
            VDF_beta1 = 4
            VDF_penalty1 = transferring_penalty(
                physical_node_df.iloc[i].node_type, neighboring_node_df.iloc[j].node_type)
            # penalty of transferring
            cost = 60
            geometry = 'LINESTRING (' + str(from_node_lon) + ' ' + str(from_node_lat) + ', ' + \
                str(to_node_lon) + ' ' + str(to_node_lat) + ')'
            agency_name = ""
            allowed_use = allowed_use_transferring(
                physical_node_df.iloc[i].node_type, neighboring_node_df.iloc[j].node_type)
            stop_sequence = ""
            directed_service_id = ""
            link_list = [link_id, from_node_id, to_node_id, facility_type, dir_flag, directed_route_id,
                         link_type, link_type_name, length, lanes, capacity, free_speed, cost,
                         VDF_fftt1, VDF_cap1, VDF_alpha1, VDF_beta1, VDF_penalty1, geometry, allowed_use, agency_name,
                         stop_sequence, directed_service_id]
            all_link_list.append(link_list)
            # transferring 2
            number_of_transferring_links += 1
            geometry = 'LINESTRING (' + str(to_node_lon) + ' ' + str(to_node_lat) + ', ' + \
                str(from_node_lon) + ' ' + str(from_node_lat) + ')'
            link_id = number_of_transferring_links + 1
            link_list = [link_id, to_node_id, from_node_id, facility_type, dir_flag, directed_route_id,
                         link_type, link_type_name, length, lanes, capacity, free_speed, cost,
                         VDF_fftt1, VDF_cap1, VDF_alpha1, VDF_beta1, VDF_penalty1, geometry, allowed_use, agency_name,
                         stop_sequence, directed_service_id]
            all_link_list.append(link_list)
            number_of_transferring_links += 1
            if number_of_transferring_links % 50 == 0:
                time_end = time.time()
                print('convert ', number_of_transferring_links,
                      'transferring links successfully...', 'using time', time_end - time_start, 's')

    return all_link_list
