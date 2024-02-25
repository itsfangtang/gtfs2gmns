import pandas as pd

# 读取CSV文件
link_df = pd.read_csv('./GMNS/SF_copy/link.csv', dtype={'directed_route_id': str, 'agency_name': str, 'directed_service_id': str}, low_memory=False)
access_link_df = pd.read_csv('./GMNS/SF_copy/access_links_1000m.csv')

# 重命名access_link_df中的列，以匹配link_df的合并列名
access_link_df.rename(columns={'zone_id': 'from_node_id', 'access_node_id': 'to_node_id', 'distance': 'length'}, inplace=True)

# 合并DataFrame
# 使用pd.merge()函数，基于from_node_id和to_node_id进行左合并
merged_df = pd.merge(link_df, access_link_df[['from_node_id', 'to_node_id', 'length', 'geometry']], on=['from_node_id', 'to_node_id'], how='left', suffixes=('', '_access'))

# 更新合并后DataFrame的指定列，为新合并的行设置默认值
merged_df.loc[merged_df['length_access'].notnull(), 'facility_type'] = 'walk'
merged_df.loc[merged_df['length_access'].notnull(), 'dir_flag'] = 1
merged_df.loc[merged_df['length_access'].notnull(), 'link_type'] = 0
merged_df.loc[merged_df['length_access'].notnull(), 'link_type_name'] = 'access_link'
merged_df.loc[merged_df['length_access'].notnull(), 'lanes'] = 1
merged_df.loc[merged_df['length_access'].notnull(), 'capacity'] = 999999
merged_df.loc[merged_df['length_access'].notnull(), 'free_speed'] = 2
merged_df.loc[merged_df['length_access'].notnull(), 'cost'] = merged_df['length_access'] / 2
merged_df.loc[merged_df['length_access'].notnull(), 'VDF_fftt1'] = merged_df['length_access'] / 2
merged_df.loc[merged_df['length_access'].notnull(), 'VDF_cap1'] = 999999
merged_df.loc[merged_df['length_access'].notnull(), 'VDF_alpha1'] = 0.15
merged_df.loc[merged_df['length_access'].notnull(), 'VDF_beta1'] = 4
merged_df.loc[merged_df['length_access'].notnull(), 'VDF_penalty1'] = 0
merged_df.loc[merged_df['length_access'].notnull(), 'VDF_allowed_uses1'] = 'w'

# 用access_link的length和geometry更新原始的值，并删除临时列
merged_df['length'] = merged_df['length_access'].fillna(merged_df['length'])
merged_df['geometry'] = merged_df['geometry_access'].fillna(merged_df['geometry'])
merged_df.drop(columns=['length_access', 'geometry_access'], inplace=True)

# 显示合并后的DataFrame
print(merged_df.head())

# 可以选择保存合并后的DataFrame到新的CSV文件
merged_df.to_csv('./GMNS/SF_copy/merged_link.csv', index=False)
