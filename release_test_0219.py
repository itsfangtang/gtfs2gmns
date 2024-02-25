import gtfs2gmns as gg

path_zone = "./Bay_Area_zone.csv"    # please make sure you have zone_id, x_coord, y_coord in columns
path_node = "./GMNS/SF/physical_node.csv"    # please make sure you have node_id, x_coord, y_coord in columns

radius = 1000 # unit in meters
k_closest = 0 # if 0, generate all accessible links within radius. if 1, closest link within the radius...

access_links = gg.generate_access_link(path_zone, path_node, radius, k_closest)

access_links.to_csv("./access_link.csv", index=False)