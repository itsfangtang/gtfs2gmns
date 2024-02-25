# -*- coding:utf-8 -*-
##############################################################
# Created Date: Sunday, February 18th 2024
# Contact Info: luoxiangyong01@gmail.com
# Author/Copyright: Mr. Xiangyong Luo
##############################################################


import pandas as pd
from shapely import Point, LineString, Polygon, geometry, MultiPoint
import pyufunc as uf
from pyufunc import gmns_geo


def generate_access_link(zone_path: str,
                         node_path: str,
                         radius: float,
                         k_closest: int = 0) -> pd.DataFrame:

    # read zone and node data
    df_zone = pd.read_csv(zone_path)
    df_node = pd.read_csv(node_path)

    # check required columns for zone data and node data
    zone_required_columns = ['zone_id', 'x_coord', 'y_coord']
    node_required_columns = ['node_id', 'x_coord', 'y_coord']
    if not set(zone_required_columns).issubset(df_zone.columns):
        raise ValueError(f"zone data should contain {zone_required_columns}")

    if not set(node_required_columns).issubset(df_node.columns):
        raise ValueError(f"node data should contain {node_required_columns}")

    # filter out the real nodes
    df_node_real = df_node[df_node['directed_service_id'].isnull()]

    # Create a dictionary for the zone
    zone_dict = {}
    for i in range(len(df_zone)):
        zone_id = df_zone.loc[i]['zone_id']
        x_coord = df_zone.loc[i]['x_coord']
        y_coord = df_zone.loc[i]['y_coord']
        zone_dict[zone_id] = {"geometry": geometry.Point(x_coord, y_coord),
                              "access_points": [],
                              "access_links": []}

    # Create a dictionary for the nodes
    node_dict = {}
    for i in range(len(df_node_real)):
        node_id = df_node_real.loc[i]['node_id']
        x_coord = df_node_real.loc[i]['x_coord']
        y_coord = df_node_real.loc[i]['y_coord']
        node_dict[node_id] = geometry.Point(x_coord, y_coord)

    # create multipoint for the nodes
    nodes_multipoints = MultiPoint([node_dict[node_id] for node_id in node_dict])

    # create zone multipoints
    zone_multipoints = MultiPoint([zone_dict[zone_id]["geometry"] for zone_id in zone_dict])

    # find the closest node to each zone
    zone_access_points = uf.find_closest_points(zone_multipoints, nodes_multipoints, radius, k_closest)

    access_links = []
    # create access links
    for zone_center in zone_access_points:
        if zone_access_points[zone_center]:
            for node_id in zone_access_points[zone_center]:
                access_links.append(
                    gmns_geo.Link(
                        id=f"{zone_center.wkt}_{node_id.wkt}",
                        from_node_id=zone_center.wkt,
                        to_node_id=node_id.wkt,
                        length=uf.calc_distance_on_unit_sphere(zone_center, node_id, "meter"),
                        lanes=1,
                        free_speed=-1,
                        capacity=-1,
                        allowed_uses='auto',
                        geometry=LineString([zone_center, node_id])
                    )
                )

    return pd.DataFrame([link.as_dict() for link in access_links])
