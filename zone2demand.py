import pandas as pd

# 1. 读取zone.csv文件
zone_df = pd.read_csv('./Bay_Area_zone.csv')

# 2. 生成o_zone_id和d_zone_id的两两配对
# 使用pd.MultiIndex.from_product来生成所有可能的配对组合
zone_pairs = pd.MultiIndex.from_product([zone_df['zone_id'], zone_df['zone_id']], names=['o_zone_id', 'd_zone_id']).to_frame(index=False)

# 过滤掉自己与自己的配对
zone_pairs = zone_pairs[zone_pairs['o_zone_id'] != zone_pairs['d_zone_id']]

# 3. 为每对配对设置volume值为10
zone_pairs['volume'] = 10

# 显示结果
print(zone_pairs)

zone_pairs.to_csv('./demand.csv', index=False)
