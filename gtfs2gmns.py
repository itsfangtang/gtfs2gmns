import copy
import os
import math
import datetime
import numpy as np
import pandas as pd
import time

pd.set_option('display.max_columns', 100)
pd.set_option('display.max_rows', 100)


def reading_data(gtfs_path, period_start_time, period_end_time):
    print('start reading input GTFS files...')
    agency_df = _reading_text(gtfs_path + os.sep + 'agency')
    agency_name = agency_df['agency_name'][0]
    if '"' in agency_name:
        agency_name = eval(agency_name)
        #  Remove quotes from string, for example '"Arlington Transit"' --> 'Arlington Transit'
    print("agent_name:", agency_name)

    stop_df = _reading_text(gtfs_path + os.sep + 'stops')
    stop_df = stop_df[['stop_id', 'stop_name', 'stop_lat', 'stop_lon']]
    print("number of stops =", len(stop_df))
    #  select only latitude and longitude of the stops/stations

    route_df = _reading_text(gtfs_path + os.sep + 'routes')
    route_df = route_df[['route_id', 'route_short_name', 'route_long_name', 'route_type']]
    print("number of routes =", len(route_df))

    trip_df = _reading_text(gtfs_path + os.sep + 'trips')

    if 'direction_id' not in trip_df.columns.tolist():  # direction_id is mandatory field name here
        trip_df['direction_id'] = str(0)

    # Deal with special issues of direction_id exists but all values are NaN
    try:
        trip_df['direction_id'] = trip_df.apply(lambda x: str(2 - int(x['direction_id'])), axis=1)
    except Exception:
        trip_df['direction_id'] = "0"

    directed_route_id = trip_df['route_id'].astype(str).str.cat(
        trip_df['direction_id'].astype(str), sep='.')
    trip_df['directed_route_id'] = directed_route_id  # add a new column "directed_route_id"
    #  If trips on a route service opposite directions,distinguish directions using values 0 and 1.
    # revise the direction_id from 0,1 to 2,1
    # add a new field directed_route_id
    # deal with special issues of Agency 12 Fairfax CUE # Alicia, Nov 10:
    # route file has route id with quotes, e.g., '"green2"' while trip file does not have it, e.g.,'green2'
    if (route_df['route_id'][0][0] == '"') != (trip_df['route_id'][0][0] == '"'):
        if route_df['route_id'][0][0] == '"':
            route_df['route_id'] = route_df.apply(lambda x: x['route_id'].strip('"'), axis=1)
        else:
            trip_df['route_id'] = trip_df.apply(lambda x: x['route_id'].strip('"'), axis=1)
    trip_route_df = pd.merge(trip_df, route_df, on='route_id')  # might go wrong in Agency 12
    print("number of trips =", len(trip_route_df), "...", len(trip_df))
    #  as route is higher level planning than trips, len(trip_route_df)=len(trip_df)

    stop_time_df = _reading_text(gtfs_path + os.sep + 'stop_times')
    print("number of stop_time records =", len(stop_time_df))
    # strip quotes from string values (e.g. Sao Paulo: "1" -> 1)
    for col in ('stop_sequence', 'arrival_time', 'departure_time'):
        if col in stop_time_df.columns:
            stop_time_df[col] = stop_time_df[col].astype(str).str.strip().str.strip('"')
    # drop the stations without accurate arrival and departure time.

    # drop nan
    stop_time_df = stop_time_df.dropna(subset=['arrival_time'], how='any')
    # drop ''
    stop_time_df = stop_time_df[stop_time_df.arrival_time != '']
    stop_time_df = stop_time_df[stop_time_df.departure_time != '']

    # drop ' '
    stop_time_df = stop_time_df[stop_time_df.arrival_time != ' ']
    stop_time_df = stop_time_df[stop_time_df.departure_time != ' ']
    print("number of stop_time records after dropping empty arrival and departure time =", len(stop_time_df))

    # convert timestamp to minute
    # as some agencies might have trips overlapping two days, should use _to_timedelta to convert the data
    print("start converting the time stamps...")
    tt = datetime.datetime(2021, 1, 1, 0, 0, 0, 0)
    stop_time_df['arrival_time'] = pd.to_timedelta(stop_time_df['arrival_time']) + tt
    stop_time_df['departure_time'] = pd.to_timedelta(stop_time_df['departure_time']) + tt
    stop_time_df['arrival_time'] = \
        stop_time_df['arrival_time'].apply(lambda x: x.hour * 60 + x.minute + 1440 * (x.day - 1))
    stop_time_df['departure_time'] = \
        stop_time_df['departure_time'].apply(lambda x: x.hour * 60 + x.minute + 1440 * (x.day - 1))

    print("start marking terminal flags for stops...")
    iteration_group = stop_time_df.groupby(['trip_id'])
    # mark terminal flag for each stop. The terminals can only be determined at the level of trips
    input_list = []
    time_start = time.time()
    for trip_id, trip_stop_time_df in iteration_group:
        trip_stop_time_df = trip_stop_time_df.sort_values(by=['stop_sequence'])
        trip_stop_time_df = trip_stop_time_df.reset_index()
        # select only the trips within the provided time window
        if (trip_stop_time_df.arrival_time.min() <= period_end_time) & (
                trip_stop_time_df.arrival_time.min() >= period_start_time):
            input_list.append(trip_stop_time_df)
    intermediate_output_list = list(map(_determine_terminal_flag, input_list))
    output_list = list(map(_stop_sequence_label, intermediate_output_list))

    # use map function to speed up marking process
    time_end = time.time()
    print('add terminal_flag for trips using CPU time:', time_end - time_start, 's')

    time_start = time.time()
    stop_time_df_with_terminal = pd.concat(output_list, axis=0)
    # concatenating a list is much faster than concatenating separate dataframes
    time_end = time.time()
    print('concatenate different trips using CPU time:', time_end - time_start, 's')
    print("have updated", len(stop_time_df_with_terminal), "stop_time records")
    print("merge the route information with trip information...")
    directed_trip_route_stop_time_df = pd.merge(trip_route_df, stop_time_df_with_terminal, on='trip_id')
    print("number of final merged records =", len(directed_trip_route_stop_time_df))
    print("Data reading done..")

    #  as trip is higher level planning than stop time scheduling, len(stop_time_df)>=len(trip_df)
    #  Each record of directed_trip_route_stop_time_df represents a space-time state of a vehicle
    # trip_id (different vehicles, e.g., train lines)
    # stop_id (spatial location of the vehicle)
    # arrival_time,departure_time (time index of the vehicle)

    directed_route_stop_id = directed_trip_route_stop_time_df['directed_route_id'].astype(
        str).str.cat(directed_trip_route_stop_time_df['stop_id'].astype(str), sep='.')
    directed_trip_route_stop_time_df['directed_route_stop_id'] = directed_route_stop_id
    #  directed_route_stop_id is a unique id to identify the route, direction, and stop of a vehicle at a time point
    directed_trip_route_stop_time_df['stop_sequence'] \
        = directed_trip_route_stop_time_df['stop_sequence'].astype('int32')
    # two important concepts : 1 directed_service_stop_id (directed_route_stop_id + stop sequence)
    directed_trip_route_stop_time_df['directed_service_stop_id'] = \
        directed_trip_route_stop_time_df.directed_route_stop_id.astype(str) + ':' + \
        directed_trip_route_stop_time_df.stop_sequence_label
    # 2. directed service id (directed_route_id + stop sequence) same directed route id might have different sequences
    directed_trip_route_stop_time_df['directed_service_id'] = \
        directed_trip_route_stop_time_df.directed_route_id.astype(str) + ':' + \
        directed_trip_route_stop_time_df.stop_sequence_label
    #  attach stop name and geometry for stops
    directed_trip_route_stop_time_df = pd.merge(directed_trip_route_stop_time_df, stop_df, on='stop_id')
    directed_trip_route_stop_time_df['agency_name'] = agency_name

    return stop_df, route_df, trip_df, trip_route_df, stop_time_df, directed_trip_route_stop_time_df


def _single_column(df, name):
    """Get a single Series from df[name]; if duplicate columns exist, take first."""
    c = df[name]
    return c.iloc[:, 0] if isinstance(c, pd.DataFrame) else c


def create_nodes(directed_trip_route_stop_time_df, agency_num):
    """create physical (station) node..."""
    physical_node_df = pd.DataFrame()
    temp_df = directed_trip_route_stop_time_df.drop_duplicates(subset=['stop_id'])
    physical_node_df['name'] = _single_column(temp_df, 'stop_id')
    physical_node_df = physical_node_df.sort_values(by=['name'])
    physical_node_df['node_id'] = \
        np.linspace(start=1, stop=len(physical_node_df), num=len(physical_node_df)).astype('int32')
    physical_node_df['node_id'] += int('{}000000'.format(agency_num))
    physical_node_df['physical_node_id'] = physical_node_df['node_id']
    physical_node_df['x_coord'] = _single_column(temp_df, 'stop_lon').astype(float)
    physical_node_df['y_coord'] = _single_column(temp_df, 'stop_lat').astype(float)
    physical_node_df['route_type'] = _single_column(temp_df, 'route_type')
    physical_node_df['route_id'] = _single_column(temp_df, 'route_id')
    physical_node_df['node_type'] = \
        physical_node_df.apply(lambda x: _convert_route_type_to_node_type_p(x.route_type), axis=1)
    physical_node_df['directed_route_id'] = ""
    physical_node_df['directed_service_id'] = ""
    physical_node_df['zone_id'] = ""
    physical_node_df['agency_name'] = _single_column(temp_df, 'agency_name')
    physical_node_df['geometry'] = 'POINT (' + physical_node_df['x_coord'].astype(str) + \
                                   ' ' + physical_node_df['y_coord'].astype(str) + ')'
    stop_name_id_dict = dict(zip(physical_node_df['name'], physical_node_df['node_id']))
    physical_node_df['terminal_flag'] = _single_column(temp_df, 'terminal_flag')
    physical_node_df['ctrl_type'] = ""
    physical_node_df['agent_type'] = ""

    """ create service node..."""
    service_node_df = pd.DataFrame()
    temp_df = directed_trip_route_stop_time_df.drop_duplicates(subset=['directed_service_stop_id'])
    # 2.2.2 route stop node
    service_node_df['name'] = temp_df['directed_service_stop_id']
    service_node_df = service_node_df.sort_values(by=['name'])
    service_node_df['node_id'] = \
        np.linspace(start=1, stop=len(service_node_df), num=len(service_node_df)).astype('int32')
    stop_id_ser = _single_column(temp_df, 'stop_id')
    service_node_df['physical_node_id'] = stop_id_ser.map(stop_name_id_dict)
    service_node_df['node_id'] += int('{}500000'.format(agency_num))

    service_node_df['x_coord'] = _single_column(temp_df, 'stop_lon').astype(float) - 0.000100
    service_node_df['y_coord'] = _single_column(temp_df, 'stop_lat').astype(float) - 0.000100
    service_node_df['route_type'] = _single_column(temp_df, 'route_type')
    service_node_df['route_id'] = _single_column(temp_df, 'route_id')
    service_node_df['node_type'] = \
        service_node_df.apply(lambda x: _convert_route_type_to_node_type_s(x.route_type), axis=1)
    service_node_df['directed_route_id'] = _single_column(temp_df, 'directed_route_id').astype(str)
    service_node_df['directed_service_id'] = _single_column(temp_df, 'directed_service_id').astype(str)
    service_node_df['zone_id'] = ""
    service_node_df['agency_name'] = _single_column(temp_df, 'agency_name')
    service_node_df['geometry'] = \
        'POINT (' + service_node_df['x_coord'].astype(str) + ' ' + service_node_df['y_coord'].astype(str) + ')'

    service_node_df['terminal_flag'] = _single_column(temp_df, 'terminal_flag')
    service_node_df['ctrl_type'] = ""
    service_node_df['agent_type'] = ""
    # concatenate service and physical node
    node_df = pd.concat([physical_node_df, service_node_df])
    return node_df


def create_service_boarding_links(directed_trip_route_stop_time_df, node_df, agency_num, one_agency_link_list,
                                   period_start_time, period_end_time, max_boarding_wait_minutes=10):
    """dictionaries"""
    node_id_dict = dict(zip(node_df['name'], node_df['node_id']))
    directed_service_dict = dict(zip(node_df['node_id'], node_df['name']))
    node_lon_dict = dict(zip(node_df['node_id'], node_df['x_coord']))
    node_lat_dict = dict(zip(node_df['node_id'], node_df['y_coord']))
    frequency_dict = {}

    print("1. start creating route links...")
    """service links"""
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
            frequency_dict[directed_service_id] = number_of_trips  # note the frequency of routes
            one_line_df = route_df[route_df.trip_id == route_df.trip_id.unique()[0]]
            one_line_df = one_line_df.sort_values(by=['stop_sequence'])
            number_of_records = len(one_line_df)
            one_line_df = one_line_df.reset_index()
            for k in range(number_of_records - 1):
                link_id = 1000000 * agency_num + number_of_route_links + 1
                from_node_id = node_id_dict[one_line_df.iloc[k].directed_service_stop_id]
                to_node_id = node_id_dict[one_line_df.iloc[k + 1].directed_service_stop_id]
                facility_type = _convert_route_type_to_link_type(one_line_df.iloc[k].route_type)
                dir_flag = 1
                directed_route_id = one_line_df.iloc[k].directed_route_id
                link_type = 1
                link_type_name = 'service_links'
                # Use service node coordinates for geometry (not physical stop)
                from_node_lon = float(node_lon_dict[from_node_id])
                from_node_lat = float(node_lat_dict[from_node_id])
                to_node_lon = float(node_lon_dict[to_node_id])
                to_node_lat = float(node_lat_dict[to_node_id])
                length = _calculate_distance_from_geometry(from_node_lon, from_node_lat, to_node_lon, to_node_lat)
                lanes = number_of_trips
                capacity = 999999
                VDF_fftt1 = one_line_df.iloc[k + 1].arrival_time - one_line_df.iloc[k].arrival_time
                # minutes
                VDF_cap1 = lanes * capacity
                free_speed = ((length / 1000) / (VDF_fftt1 + 0.001)) * 60
                # (kilometers/minutes)*60 = kilometer/hour
                VDF_alpha1 = 0.15
                VDF_beta1 = 4
                VDF_penalty1 = 0
                cost = 0
                geometry = 'LINESTRING (' + str(from_node_lon) + ' ' + str(from_node_lat) + ', ' + \
                           str(to_node_lon) + ' ' + str(to_node_lat) + ')'
                agency_name = one_line_df.agency_name[0]
                allowed_use = _allowed_use_function(one_line_df.iloc[k].route_type)
                stop_sequence = one_line_df.iloc[k].stop_sequence
                directed_service_id = one_line_df.iloc[k].directed_service_id
                link_list = [link_id, from_node_id, to_node_id, facility_type, dir_flag, directed_route_id,
                             link_type, link_type_name, length, lanes, capacity, free_speed, cost,
                             VDF_fftt1, VDF_cap1, VDF_alpha1, VDF_beta1, VDF_penalty1, geometry, allowed_use,
                             agency_name,
                             stop_sequence, directed_service_id]
                one_agency_link_list.append(link_list)
                number_of_route_links += 1
                if number_of_route_links % 50 == 0:
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
        facility_type = _convert_route_type_to_link_type(row.route_type)
        dir_flag = 1
        directed_route_id = row.directed_route_id
        link_type = 2
        to_node_lon = row.x_coord
        to_node_lat = row.y_coord
        from_node_lon = node_lon_dict[row.physical_node_id]
        from_node_lat = node_lat_dict[row.physical_node_id]
        length = _calculate_distance_from_geometry(from_node_lon, from_node_lat, to_node_lon, to_node_lat)
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
        allowed_use = _allowed_use_function(row.route_type)

        # inbound: physical node -> service node (boarding)
        link_type_name = 'boarding_links'
        VDF_fftt1 = \
            0.5 * ((period_end_time - period_start_time) / frequency_dict[row.directed_service_id])
        VDF_fftt1 = min(VDF_fftt1, max_boarding_wait_minutes)
        geometry_inbound = 'LINESTRING (' + str(from_node_lon) + ' ' + str(from_node_lat) + ', ' + \
                           str(to_node_lon) + ' ' + str(to_node_lat) + ')'
        link_list_inbound = [link_id, from_node_id, to_node_id, facility_type, dir_flag, directed_route_id,
                             link_type, link_type_name, length, lanes, capacity, free_speed, cost,
                             VDF_fftt1, VDF_cap1, VDF_alpha1, VDF_beta1, VDF_penalty1, geometry_inbound, allowed_use,
                             agency_name,
                             stop_sequence, directed_service_id]
        number_of_sta2route_links += 1

        # outbound: service node -> physical node (deboarding)
        link_id = agency_num * 1000000 + number_of_route_links + number_of_sta2route_links
        link_type_name = 'deboarding_links'
        VDF_fftt1 = 0  # no waiting time for deboarding
        geometry_outbound = 'LINESTRING (' + str(to_node_lon) + ' ' + str(to_node_lat) + ', ' + \
                            str(from_node_lon) + ' ' + str(from_node_lat) + ')'
        link_list_outbound = [link_id, to_node_id, from_node_id, facility_type, dir_flag, directed_route_id,
                              link_type, link_type_name, length, lanes, capacity, free_speed, cost,
                              VDF_fftt1, VDF_cap1, VDF_alpha1, VDF_beta1, VDF_penalty1, geometry_outbound, allowed_use,
                              agency_name,
                              stop_sequence, directed_service_id]
        one_agency_link_list.append(link_list_inbound)
        one_agency_link_list.append(link_list_outbound)
        number_of_sta2route_links += 1
        #  one inbound link and one outbound link
        if number_of_sta2route_links % 50 == 0:
            time_end = time.time()
            print('convert ', number_of_sta2route_links,
                  'boarding links successfully...', 'using time', time_end - time_start, 's')

    return one_agency_link_list


def create_transferring_links(all_node_df, all_link_list, transfer_bbox_deg=0.003, transfer_min_m=1.0, transfer_max_m=321.869):
    physical_node_df = all_node_df[all_node_df.node_id == all_node_df.physical_node_id]
    physical_node_df = physical_node_df.reset_index()
    number_of_transferring_links = 0
    time_start = time.time()
    for i in range(len(physical_node_df)):
        ref_x = physical_node_df.iloc[i].x_coord
        ref_y = physical_node_df.iloc[i].y_coord
        neighboring_node_df = physical_node_df[(physical_node_df.x_coord >= (ref_x - transfer_bbox_deg)) &
                                               (physical_node_df.x_coord <= (ref_x + transfer_bbox_deg))]
        neighboring_node_df = neighboring_node_df[(neighboring_node_df.y_coord >= (ref_y - transfer_bbox_deg)) &
                                                  (neighboring_node_df.y_coord <= (ref_y + transfer_bbox_deg))]
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
            length = _calculate_distance_from_geometry(from_node_lon, from_node_lat, to_node_lon, to_node_lat)
            if (length > transfer_max_m) | (length < transfer_min_m):
                continue
            if (neighboring_node_df.iloc[j].route_id, neighboring_node_df.iloc[j].agency_name) in labeled_list:
                continue
            count += 1
            labeled_list.append((neighboring_node_df.iloc[j].route_id, neighboring_node_df.iloc[j].agency_name))
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
            VDF_penalty1 = _transferring_penalty(physical_node_df.iloc[i].node_type,
                                                 neighboring_node_df.iloc[j].node_type)
            # penalty of transferring
            cost = 60
            geometry = 'LINESTRING (' + str(from_node_lon) + ' ' + str(from_node_lat) + ', ' + \
                       str(to_node_lon) + ' ' + str(to_node_lat) + ')'
            agency_name = ""
            allowed_use = \
                _allowed_use_transferring(physical_node_df.iloc[i].node_type, neighboring_node_df.iloc[j].node_type)
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


""" ------------------functions------------------ """


def _stop_sequence_label(trip_stop_time_df):
    trip_stop_time_df = trip_stop_time_df.sort_values(by=['stop_sequence'])
    trip_stop_time_df['stop_sequence_label'] = ';'.join(np.array(trip_stop_time_df.stop_sequence).astype(str))
    return trip_stop_time_df


def _normalize_column_name(s):
    """Strip whitespace and double quotes from column name (e.g. '"stop_id"' -> 'stop_id')."""
    if not isinstance(s, str):
        s = str(s)
    return s.strip().strip('"').strip()


def _normalize_cell(s):
    """Strip whitespace and double quotes from cell value (e.g. '"9.16"' -> '9.16')."""
    if not isinstance(s, str):
        s = str(s)
    return s.strip().strip('"').strip()


def _reading_text(filename):
    file_path = filename + '.txt'
    with open(file_path, 'r', encoding='utf-8-sig') as f:
        lines = f.readlines()
    # Parse every line with quote-aware split so column count is consistent (fixes Chicago)
    data = []
    for line in lines:
        line_clean = line.split('\n')[0].strip()
        if not line_clean:
            continue
        data.append(_split_ignore_separators_in_quoted(line_clean))
    if not data:
        return pd.DataFrame()
    raw_columns = data[0]
    norm_columns = [_normalize_column_name(c) for c in raw_columns]
    # Keep first occurrence of each column name (drop duplicate columns -> fixes Sao Paulo / Prague)
    columns = []
    col_indices = []
    seen = set()
    for i, c in enumerate(norm_columns):
        if c not in seen:
            seen.add(c)
            columns.append(c)
            col_indices.append(i)
    ncol = len(columns)
    # Normalize cell values (fixes Milan, Hamburg, Vienna, Berlin quoted numbers)
    data_rows = []
    for row in data[1:]:
        cells = [_normalize_cell(row[j]) if j < len(row) else '' for j in col_indices]
        data_rows.append(cells)
    data_frame = pd.DataFrame(data_rows, columns=columns)
    return data_frame


def _determine_terminal_flag(trip_stop_time_df):
    trip_stop_time_df.stop_sequence = trip_stop_time_df.stop_sequence.astype('int32')
    start_stop_seq = int(trip_stop_time_df.stop_sequence.min())
    end_stop_seq = int(trip_stop_time_df.stop_sequence.max())
    #  convert string to integer
    trip_stop_time_df['terminal_flag'] = \
        ((trip_stop_time_df.stop_sequence == start_stop_seq) |
         (trip_stop_time_df.stop_sequence == end_stop_seq)).astype('int32')
    return trip_stop_time_df


def _allowed_use_function(route_type):
    allowed_use = ""
    rt = _safe_route_type(route_type)
    if rt == 0:
        allowed_use = "w_bus_only;w_bus_metro;d_bus_only;d_bus_metro"
    if rt == 1:
        allowed_use = "w_metro_only;w_bus_metro;d_metro_only;d_bus_metro"
    if rt == 2:
        allowed_use = "w_rail_only;d_rail_only"
    if rt == 3:
        allowed_use = "w_bus_only;w_bus_metro;d_bus_only;d_bus_metro"
    return allowed_use


def _allowed_use_transferring(node_type_1, node_type_2):
    if (node_type_1 == 'stop') & (node_type_2 == 'stop'):
        allowed_use = "w_bus_only;d_bus_only"
    elif (node_type_1 == 'stop') & (node_type_2 == 'metro_station'):
        allowed_use = "w_bus_metro;d_bus_metro"
    elif (node_type_1 == 'metro_station') & (node_type_2 == 'stop'):
        allowed_use = "w_bus_metro;d_bus_metro"
    elif (node_type_1 == 'metro_station') & (node_type_2 == 'metro_station'):
        allowed_use = "w_metro_only;d_metro_only"
    elif (node_type_1 == 'rail_station') & (node_type_2 == 'rail_station'):
        allowed_use = "w_rail_only;d_rail_only"
    else:
        allowed_use = "closed"

    return allowed_use


def _transferring_penalty(node_type_1, node_type_2):
    if (node_type_1 == 'stop') & (node_type_2 == 'stop'):
        VDF_penalty1 = 99
    elif (node_type_1 == 'stop') & (node_type_2 == 'metro_station'):
        VDF_penalty1 = 0
    elif (node_type_1 == 'metro_station') & (node_type_2 == 'stop'):
        VDF_penalty1 = 0
    elif (node_type_1 == 'metro_station') & (node_type_2 == 'metro_station'):
        VDF_penalty1 = 99
    elif (node_type_1 == 'rail_station') & (node_type_2 == 'rail_station'):
        VDF_penalty1 = 99
    else:
        VDF_penalty1 = 1000

    return VDF_penalty1


def _safe_route_type(route_type):
    """Convert route_type to int, handling quotes, whitespace, and Series/array."""
    if hasattr(route_type, 'iloc'):
        route_type = route_type.iloc[0]
    elif hasattr(route_type, '__len__') and not isinstance(route_type, (str, bytes)):
        try:
            route_type = route_type[0]
        except (IndexError, KeyError, TypeError):
            pass
    s = str(route_type).strip().strip('"').strip()
    try:
        return int(float(s)) if s else 3
    except (ValueError, TypeError):
        return 3  # default bus


def _convert_route_type_to_node_type_p(route_type):
    #  convert route type to node type on physical network
    node_type = ""
    rt = _safe_route_type(route_type)
    if rt == 0:
        # tram
        node_type = 'stop'
    if rt == 1:
        # metro
        node_type = 'metro_station'
    if rt == 2:
        # rail
        node_type = 'rail_station'
    if rt == 3:
        # bus
        node_type = 'stop'
    return node_type


def _convert_route_type_to_node_type_s(route_type):
    #  convert route type to node type on service network
    node_type = ""
    rt = _safe_route_type(route_type)
    if rt == 0:
        node_type = 'tram_service_node'
    if rt == 1:
        node_type = 'metro_service_node'
    if rt == 2:
        node_type = 'rail_service_node'
    if rt == 3:
        node_type = 'bus_service_node'
    return node_type


def _convert_route_type_to_link_type(route_type):
    link_type = ""
    rt = _safe_route_type(route_type)
    if rt == 0:
        link_type = 'tram'
    if rt == 1:
        link_type = 'metro'
    if rt == 2:
        link_type = 'rail'
    if rt == 3:
        link_type = 'bus'
    return link_type


def _split_ignore_separators_in_quoted(s, separator=',', quote_mark='"'):
    result = []
    quoted = False
    current = ''
    for i in range(len(s)):
        if quoted:
            current += s[i]
            if s[i] == quote_mark:
                quoted = False
            continue
        if s[i] == separator:
            result.append(current.strip())
            current = ''
        else:
            current += s[i]
            if s[i] == quote_mark:
                quoted = True
    result.append(current)
    return result


def _calculate_distance_from_geometry(lon1, lat1, lon2, lat2):  # WGS84 transfer coordinate system to distance(mile) #xy
    radius = 6371
    d_latitude = (lat2 - lat1) * math.pi / 180.0
    d_longitude = (lon2 - lon1) * math.pi / 180.0

    a = math.sin(d_latitude / 2) * math.sin(d_latitude / 2) + math.cos(lat1 * math.pi / 180.0) * math.cos(
        lat2 * math.pi / 180.0) * math.sin(d_longitude / 2) * math.sin(d_longitude / 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    # distance = radius * c * 1000 / 1609.34  # mile
    distance = radius * c * 1000  # meter
    return distance


def _build_gtfs_gmns_statistics(
    num_agencies, all_stop_df, all_route_df, all_trip_route_df, all_stop_time_df, all_directed_df,
    all_node_df, all_link_df, period_start_min, period_end_min, generate_transferring_links,
    first_gtfs_path=None,
    transfer_bbox_deg=0.003, transfer_min_m=1.0, transfer_max_m=321.869,
):
    """
    Build a teachable GTFS→GMNS QA summary (statistic.csv).
    Sections: (1) GTFS inventory, (2) Temporal service window, (3) Frequency & structure,
    (4) Spatial/mileage, (5) GMNS mapping, (6) Transfer logic, (7) Error-check counters.
    """
    def _to_float(s, default=np.nan):
        try:
            return float(s)
        except (ValueError, TypeError):
            return default

    rows = []
    last_section = [None]
    def add(section, statistic, value):
        s = section if section != last_section[0] else ''
        rows.append((s, statistic, value))
        last_section[0] = section

    # ----- 1) GTFS inventory (raw feed) -----
    add('1_GTFS_inventory', 'Number of agencies in the feed', num_agencies)
    add('1_GTFS_inventory', 'Number of routes', len(all_route_df))
    add('1_GTFS_inventory', 'Number of trips', len(all_trip_route_df))
    add('1_GTFS_inventory', 'Number of stops', len(all_stop_df))
    add('1_GTFS_inventory', 'Number of stop time records', len(all_stop_time_df))
    num_shapes = 'N/A'
    num_service_ids = 'N/A'
    if first_gtfs_path:
        for name in ['shapes', 'calendar']:
            path = os.path.join(first_gtfs_path, name + '.txt')
            if os.path.isfile(path):
                try:
                    df = _reading_text(first_gtfs_path + os.sep + name)
                    n = len(df)
                    if name == 'shapes':
                        num_shapes = n
                        if 'shape_id' in all_trip_route_df.columns:
                            trips_with_shape = all_trip_route_df['shape_id'].notna() & (all_trip_route_df['shape_id'].astype(str).str.strip() != '')
                            pct = 100.0 * trips_with_shape.sum() / len(all_trip_route_df) if len(all_trip_route_df) else 0
                            add('1_GTFS_inventory', 'Share of trips that have a shape (percent)', round(pct, 2))
                        else:
                            add('1_GTFS_inventory', 'Share of trips that have a shape (percent)', 'N/A')
                    else:
                        num_service_ids = n
                except Exception:
                    pass
    add('1_GTFS_inventory', 'Number of shape records', num_shapes)
    add('1_GTFS_inventory', 'Number of service IDs in calendar', num_service_ids)

    # ----- 2) Temporal service window (conversion window) -----
    add('2_temporal_service_window', 'Start of conversion time window (minutes from midnight)', period_start_min)
    add('2_temporal_service_window', 'End of conversion time window (minutes from midnight)', period_end_min)
    add('2_temporal_service_window', 'Length of time window in minutes', period_end_min - period_start_min)
    add('2_temporal_service_window', 'Length of time window in hours', round((period_end_min - period_start_min) / 60.0, 2))
    if len(all_directed_df):
        dep = all_directed_df.groupby('trip_id')['departure_time'].min()
        arr = all_directed_df.groupby('trip_id')['arrival_time'].max()
        add('2_temporal_service_window', 'Earliest trip departure in window (minutes from midnight)', int(dep.min()))
        add('2_temporal_service_window', 'Latest trip arrival in window (minutes from midnight)', int(arr.max()))
        add('2_temporal_service_window', 'Number of trips that fall within the time window', len(dep))

    # ----- 3) Frequency & structure (in-window) -----
    if len(all_directed_df):
        by_route = all_directed_df.groupby('directed_route_id')
        trips_per_route = by_route['trip_id'].nunique()
        stops_per_route = by_route['stop_id'].nunique()
        runtime_per_trip = all_directed_df.groupby('trip_id').apply(
            lambda g: g['arrival_time'].max() - g['arrival_time'].min() if len(g) else 0
        )
        add('3_frequency_structure', 'Median number of trips per directed route in window', float(np.median(trips_per_route)))
        add('3_frequency_structure', 'Median number of stops per route', float(np.median(stops_per_route)))
        add('3_frequency_structure', 'Median trip runtime in minutes', float(np.median(runtime_per_trip)))
        period_min = period_end_min - period_start_min
        headways = period_min / (trips_per_route.replace(0, np.nan))
        add('3_frequency_structure', 'Median headway in minutes', float(np.nanmedian(headways)))
        valid_h = headways.dropna()
        if len(valid_h):
            add('3_frequency_structure', '10th percentile headway in minutes', round(float(np.nanpercentile(headways, 10)), 2))
            add('3_frequency_structure', '90th percentile headway in minutes', round(float(np.nanpercentile(headways, 90)), 2))

    # ----- 4) Spatial / mileage -----
    if 'stop_lat' in all_stop_df.columns and 'stop_lon' in all_stop_df.columns:
        lat = all_stop_df['stop_lat'].apply(_to_float)
        lon = all_stop_df['stop_lon'].apply(_to_float)
        valid = lat.notna() & lon.notna()
        add('4_spatial', 'Share of stops with valid latitude and longitude (percent)', round(100.0 * valid.sum() / len(all_stop_df), 2) if len(all_stop_df) else 0)
        add('4_spatial', 'Number of stops missing valid coordinates', int((~valid).sum()))
        if valid.any():
            add('4_spatial', 'Bounding box minimum latitude', round(float(lat[valid].min()), 6))
            add('4_spatial', 'Bounding box maximum latitude', round(float(lat[valid].max()), 6))
            add('4_spatial', 'Bounding box minimum longitude', round(float(lon[valid].min()), 6))
            add('4_spatial', 'Bounding box maximum longitude', round(float(lon[valid].max()), 6))
    if len(all_directed_df) and 'stop_lat' in all_directed_df.columns and 'stop_lon' in all_directed_df.columns:
        seg_dist = 0.0
        for tid, grp in all_directed_df.groupby('trip_id'):
            g = grp.sort_values('stop_sequence')
            lats = g['stop_lat'].astype(float)
            lons = g['stop_lon'].astype(float)
            for i in range(len(g) - 1):
                seg_dist += _calculate_distance_from_geometry(
                    lons.iloc[i], lats.iloc[i], lons.iloc[i + 1], lats.iloc[i + 1])
        add('4_spatial', 'Total vehicle distance in window, stop to stop (meters)', round(seg_dist, 2))
        add('4_spatial', 'Total vehicle distance in window, stop to stop (kilometers)', round(seg_dist / 1000.0, 2))

    # ----- 5) GMNS mapping summary -----
    add('5_GMNS_mapping', 'Total number of nodes in GMNS network', len(all_node_df))
    num_physical = int((all_node_df['node_id'] == all_node_df['physical_node_id']).sum())
    num_service = int((all_node_df['node_id'] != all_node_df['physical_node_id']).sum())
    add('5_GMNS_mapping', 'Number of physical stop nodes', num_physical)
    add('5_GMNS_mapping', 'Number of service nodes', num_service)
    if num_physical > 0:
        add('5_GMNS_mapping', 'Average service nodes per physical stop', round(num_service / num_physical, 2))
    for nt, cnt in all_node_df['node_type'].value_counts().sort_index().items():
        add('5_GMNS_mapping', 'Number of nodes (type: ' + str(nt) + ')', int(cnt))
    add('5_GMNS_mapping', 'Total number of links in GMNS network', len(all_link_df))
    for lt, cnt in all_link_df['link_type_name'].value_counts().sort_index().items():
        add('5_GMNS_mapping', 'Number of links (type: ' + str(lt) + ')', int(cnt))
    routes_in_gmns = all_node_df['directed_route_id'].dropna()
    routes_in_gmns = routes_in_gmns[routes_in_gmns.astype(str).str.strip() != '']
    n_routes_gmns = routes_in_gmns.nunique() if len(routes_in_gmns) else 0
    add('5_GMNS_mapping', 'Number of directed routes represented in GMNS', n_routes_gmns)
    if 'directed_route_id' in all_trip_route_df.columns:
        n_routes_gtfs = all_trip_route_df['directed_route_id'].nunique()
        add('5_GMNS_mapping', 'Number of directed routes in GTFS feed', n_routes_gtfs)

    # ----- 6) Transfer logic -----
    add('6_transfer_logic', 'Whether transferring links were generated', generate_transferring_links)
    add('6_transfer_logic', 'Spatial search window for transfer pairs (degrees)', transfer_bbox_deg)
    add('6_transfer_logic', 'Minimum distance for a transfer link (meters)', transfer_min_m)
    add('6_transfer_logic', 'Maximum distance for a transfer link (meters)', transfer_max_m)
    if generate_transferring_links and 'transferring_links' in all_link_df['link_type_name'].values:
        tr = all_link_df[all_link_df['link_type_name'] == 'transferring_links'].copy()
        from_ids = tr['from_node_id'].value_counts()
        add('6_transfer_logic', 'Total number of transfer links', len(tr))
        add('6_transfer_logic', 'Average number of transfer links per stop', round(float(from_ids.mean()), 2) if len(from_ids) else 0)
        add('6_transfer_logic', 'Median number of transfer links per stop', float(from_ids.median()) if len(from_ids) else 0)
        node_types = all_node_df.set_index('node_id')['node_type'].to_dict()
        tr['from_type'] = tr['from_node_id'].map(node_types)
        tr['to_type'] = tr['to_node_id'].map(node_types)
        tr['mode_pair'] = tr.apply(lambda r: '↔'.join(sorted([str(r['from_type']), str(r['to_type'])])), axis=1)
        for pair, cnt in tr['mode_pair'].value_counts().sort_index().items():
            add('6_transfer_logic', 'Number of transfer links (mode pair: ' + str(pair) + ')', int(cnt))

    # ----- 7) Error-check counters -----
    trips_in_st = set(all_stop_time_df['trip_id'].astype(str).unique()) if 'trip_id' in all_stop_time_df.columns else set()
    trips_in_tr = set(all_trip_route_df['trip_id'].astype(str).unique()) if 'trip_id' in all_trip_route_df.columns else set()
    add('7_error_checks', 'Number of trips that have no stop times', len(trips_in_tr - trips_in_st))
    miss_stop_id = all_stop_time_df['stop_id'].isna() | (all_stop_time_df['stop_id'].astype(str).str.strip() == '')
    add('7_error_checks', 'Number of stop time records with missing or empty stop ID', int(miss_stop_id.sum()) if 'stop_id' in all_stop_time_df.columns else 'N/A')
    if 'stop_lat' in all_stop_df.columns and 'stop_lon' in all_stop_df.columns:
        lat = all_stop_df['stop_lat'].apply(_to_float)
        lon = all_stop_df['stop_lon'].apply(_to_float)
        add('7_error_checks', 'Number of stops missing valid latitude or longitude', int((lat.isna() | lon.isna()).sum()))
    dup_seq = 0
    if 'trip_id' in all_stop_time_df.columns and 'stop_sequence' in all_stop_time_df.columns:
        dup_seq = all_stop_time_df.duplicated(subset=['trip_id', 'stop_sequence']).sum()
    add('7_error_checks', 'Number of duplicated trip and stop sequence pairs', int(dup_seq))
    if first_gtfs_path and os.path.isfile(os.path.join(first_gtfs_path, 'shapes.txt')) and 'shape_id' in all_trip_route_df.columns:
        no_shape = all_trip_route_df['shape_id'].isna() | (all_trip_route_df['shape_id'].astype(str).str.strip() == '')
        add('7_error_checks', 'Number of trips without a shape (when shapes file exists)', int(no_shape.sum()))
    else:
        add('7_error_checks', 'Number of trips without a shape (when shapes file exists)', 'N/A')
    decreasing = 0
    if len(all_stop_time_df) and 'trip_id' in all_stop_time_df.columns and 'arrival_time' in all_stop_time_df.columns:
        for tid, grp in all_stop_time_df.groupby('trip_id'):
            g = grp.sort_values('stop_sequence')
            arr = pd.to_numeric(g['arrival_time'], errors='coerce')
            if arr.isna().any():
                continue
            if (arr.diff().dropna() < 0).any():
                decreasing += 1
    add('7_error_checks', 'Number of trips with backward or decreasing arrival times', int(decreasing))
    zero_dist = 0
    if len(all_directed_df) and 'stop_lat' in all_directed_df.columns and 'stop_lon' in all_directed_df.columns:
        for tid, grp in all_directed_df.groupby('trip_id'):
            g = grp.sort_values('stop_sequence')
            lats = g['stop_lat'].apply(_to_float)
            lons = g['stop_lon'].apply(_to_float)
            for i in range(len(g) - 1):
                d = _calculate_distance_from_geometry(
                    lons.iloc[i], lats.iloc[i], lons.iloc[i + 1], lats.iloc[i + 1])
                if d < 1.0:
                    zero_dist += 1
    add('7_error_checks', 'Number of consecutive stop pairs with zero or near zero distance', int(zero_dist))

    return pd.DataFrame(rows, columns=['section', 'statistic', 'value'])


def _hhmm_to_minutes(time_period_1):
    from_time_1 = datetime.time(int(time_period_1[0:2]), int(time_period_1[2:4]))
    to_time_1 = datetime.time(int(time_period_1[-4:-2]), int(time_period_1[-2:]))
    from_time_min_1 = from_time_1.hour * 60 + from_time_1.minute
    to_time_min_1 = to_time_1.hour * 60 + to_time_1.minute
    return from_time_min_1, to_time_min_1


""" ------------------main functions------------------ """


def gtfs2gmns(input_path, output_path, time_period='0700_0800', max_boarding_wait_minutes=10,
              generate_transferring_links=True, transfer_bbox_deg=0.003, transfer_min_m=1.0, transfer_max_m=321.869):
    """Convert GTFS data to GMNS network files. All parameters can be set by the user (script or config)."""
    period_start_time, period_end_time = _hhmm_to_minutes(time_period)
    start_time = time.time()
    folders = [folder for folder in os.listdir(input_path) if "check" not in folder]
    gtfs_folder_list = []
    for sub_folder in folders:
        sub_folder_path = input_path + '/' + sub_folder
        if os.path.isdir(sub_folder_path):  # check whether the specified path is an existing directory or not.
            gtfs_folder_list.append(sub_folder_path)
    if len(gtfs_folder_list) == 0:
        gtfs_folder_list.append(input_path)

    all_node_list = []
    all_link_list = []
    # Accumulate GTFS data for QA statistics (GTFS inventory, temporal, frequency, spatial, error checks)
    stop_list = []
    route_list = []
    trip_route_list = []
    stop_time_list = []
    directed_list = []
    for i in range(len(gtfs_folder_list)):
        print('Start converting Agency_{}...'.format(i + 1))
        print('Directory : ' + str(gtfs_folder_list[i]))
        agency_gtfs_path = gtfs_folder_list[i]
        """ step 1. reading data """
        stop_df, route_df, trip_df, trip_route_df, stop_time_df, directed_trip_route_stop_time_df = \
            reading_data(agency_gtfs_path, period_start_time, period_end_time)
        stop_list.append(stop_df)
        route_list.append(route_df)
        trip_route_list.append(trip_route_df)
        stop_time_list.append(stop_time_df)
        directed_list.append(directed_trip_route_stop_time_df)

        """step 2. create nodes"""
        agency_num = i + 1
        # number of agency equals to i+1
        node_df = create_nodes(directed_trip_route_stop_time_df, agency_num)
        all_node_list.append(node_df)
        print("node.csv of", str(gtfs_folder_list[i]), "has been generated...")
        """step 3. create links"""
        all_link_list = create_service_boarding_links(
            directed_trip_route_stop_time_df, node_df, agency_num, all_link_list,
            period_start_time, period_end_time, max_boarding_wait_minutes=max_boarding_wait_minutes)

        if i == len(gtfs_folder_list):
            print('output')
        print('Conversion of  Agency{}...'.format(agency_num + 1), ' have done..')

    all_node_df = pd.concat(all_node_list)
    all_node_df.reset_index(inplace=True)
    all_node_df = all_node_df.drop(['index'], axis=1)
    # transferring links (optional)
    if generate_transferring_links:
        all_link_list = create_transferring_links(
            all_node_df, all_link_list,
            transfer_bbox_deg=transfer_bbox_deg, transfer_min_m=transfer_min_m, transfer_max_m=transfer_max_m)
    else:
        print('Skipping transferring links (generate_transferring_links=False).')

    all_link_df = pd.DataFrame(all_link_list)
    all_link_df.rename(columns={0: 'link_id',
                                1: 'from_node_id',
                                2: 'to_node_id',
                                3: 'facility_type',
                                4: 'dir_flag',
                                5: 'directed_route_id',
                                6: 'link_type',
                                7: 'link_type_name',
                                8: 'length',
                                9: 'lanes',
                                10: 'capacity',
                                11: 'free_speed',
                                12: 'cost',
                                13: 'VDF_fftt',
                                14: 'VDF_cap',
                                15: 'VDF_alpha',
                                16: 'VDF_beta',
                                17: 'VDF_penalty',
                                18: 'geometry',
                                19: 'VDF_allowed_uses',
                                20: 'agency_name',
                                21: 'stop_sequence',
                                22: 'directed_service_id'}, inplace=True)
    all_node_df.to_csv(output_path + '/' + 'node.csv', index=False)
    #  zone_df = pd.read_csv('zone.csv')
    #  source_node_df = pd.read_csv('source_node.csv')
    #  node_df = pd.concat([zone_df, all_node_df])
    #  node_df.to_csv("node.csv", index=False)
    all_link_df = all_link_df.drop_duplicates(
        subset=['from_node_id', 'to_node_id'],
        keep='last').reset_index(drop=True)
    all_link_df.to_csv(output_path + '/' + 'link.csv', index=False)

    # statistic.csv: GTFS→GMNS conversion QA summary (teachable checklist)
    all_stop_df = pd.concat(stop_list, ignore_index=True).drop_duplicates(subset=['stop_id']).reset_index(drop=True)
    all_route_df = pd.concat(route_list, ignore_index=True)
    all_trip_route_df = pd.concat(trip_route_list, ignore_index=True)
    all_stop_time_df = pd.concat(stop_time_list, ignore_index=True)
    all_directed_df = pd.concat(directed_list, ignore_index=True) if directed_list else pd.DataFrame()
    first_gtfs_path = gtfs_folder_list[0] if gtfs_folder_list else None
    stat_df = _build_gtfs_gmns_statistics(
        num_agencies=len(gtfs_folder_list),
        all_stop_df=all_stop_df,
        all_route_df=all_route_df,
        all_trip_route_df=all_trip_route_df,
        all_stop_time_df=all_stop_time_df,
        all_directed_df=all_directed_df,
        all_node_df=all_node_df,
        all_link_df=all_link_df,
        period_start_min=period_start_time,
        period_end_min=period_end_time,
        generate_transferring_links=generate_transferring_links,
        first_gtfs_path=first_gtfs_path,
        transfer_bbox_deg=transfer_bbox_deg, transfer_min_m=transfer_min_m, transfer_max_m=transfer_max_m,
    )
    stat_df.to_csv(output_path + '/' + 'statistic.csv', index=False)
    print('run time -->', time.time() - start_time)


def _load_config(path):
    """Load options from a JSON config file. Returns a dict; keys match gtfs2gmns() and CLI."""
    import json
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def main():
    """Entry point for the gtfs2gmns CLI (and for python -m gtfs2gmns)."""
    import argparse
    parser = argparse.ArgumentParser(
        description='Convert GTFS transit data to GMNS network files. '
                    'Use --config to load options from a JSON file (user-customizable).'
    )
    parser.add_argument('input_path', nargs='?', default=None, help='Path to GTFS folder(s)')
    parser.add_argument('output_path', nargs='?', default=None, help='Path to output GMNS folder')
    parser.add_argument('--config', '-c', metavar='FILE', help='Load options from JSON config file (overridden by CLI args)')
    parser.add_argument('--time-period', default=None, help='Time window as HHMM_HHMM (e.g. 0700_0800)')
    parser.add_argument('--max-boarding-wait', type=float, default=None, help='Max boarding wait in minutes')
    parser.add_argument('--no-transfer-links', action='store_true', help='Do not generate transferring links')
    parser.add_argument('--transfer-bbox-deg', type=float, default=None, help='Transfer search window (degrees)')
    parser.add_argument('--transfer-min-m', type=float, default=None, help='Min transfer distance (m)')
    parser.add_argument('--transfer-max-m', type=float, default=None, help='Max transfer distance (m)')
    args = parser.parse_args()

    # Defaults (used when neither config nor CLI provides a value)
    defaults = {
        'input_path': './GTFS/BART',
        'output_path': './GMNS/BART',
        'time_period': '0700_0800',
        'max_boarding_wait_minutes': 10,
        'generate_transferring_links': True,
        'transfer_bbox_deg': 0.003,
        'transfer_min_m': 1.0,
        'transfer_max_m': 321.869,
    }

    if getattr(args, 'config', None):
        cfg = _load_config(args.config)
        # Map config keys to our names (allow both snake_case and with units)
        key_map = {
            'input_path': 'input_path', 'output_path': 'output_path',
            'time_period': 'time_period', 'max_boarding_wait_minutes': 'max_boarding_wait_minutes',
            'generate_transferring_links': 'generate_transferring_links',
            'transfer_bbox_deg': 'transfer_bbox_deg', 'transfer_min_m': 'transfer_min_m',
            'transfer_max_m': 'transfer_max_m',
        }
        for k, v in cfg.items():
            if k in key_map and v is not None:
                defaults[key_map[k]] = v
    # CLI overrides
    if args.input_path is not None:
        defaults['input_path'] = args.input_path
    if args.output_path is not None:
        defaults['output_path'] = args.output_path
    if args.time_period is not None:
        defaults['time_period'] = args.time_period
    if args.max_boarding_wait is not None:
        defaults['max_boarding_wait_minutes'] = args.max_boarding_wait
    if args.no_transfer_links:
        defaults['generate_transferring_links'] = False
    if args.transfer_bbox_deg is not None:
        defaults['transfer_bbox_deg'] = args.transfer_bbox_deg
    if args.transfer_min_m is not None:
        defaults['transfer_min_m'] = args.transfer_min_m
    if args.transfer_max_m is not None:
        defaults['transfer_max_m'] = args.transfer_max_m

    gtfs2gmns(
        defaults['input_path'],
        defaults['output_path'],
        time_period=defaults['time_period'],
        max_boarding_wait_minutes=defaults['max_boarding_wait_minutes'],
        generate_transferring_links=defaults['generate_transferring_links'],
        transfer_bbox_deg=defaults['transfer_bbox_deg'],
        transfer_min_m=defaults['transfer_min_m'],
        transfer_max_m=defaults['transfer_max_m'],
    )


if __name__ == '__main__':
    main()
