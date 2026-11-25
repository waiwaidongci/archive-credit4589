def seed() -> list[dict]:
    city_documentary = dict(archive='市影像馆', channel='纪录片发行', use_kind='素材镜头')
    coast_documentary = dict(archive='海岸档案馆', channel='纪录片发行', use_kind='素材镜头')
    city_exhibit = dict(archive='市影像馆', channel='馆内展映', use_kind='素材镜头')
    city_news = dict(archive='市影像馆', channel='馆内展映', use_kind='新闻短片')
    return [
        dict(city_documentary, row_type='contract', record_id='C-CITY',
             starts_on='2026-11-01', ends_on='2026-11-30'),
        dict(coast_documentary, row_type='contract', record_id='C-COAST',
             starts_on='2026-11-05', ends_on='2026-11-22'),
        dict(city_exhibit, row_type='contract', record_id='C-EXHIBIT',
             starts_on='2026-11-10', ends_on='2026-12-01'),
        dict(city_news, row_type='contract', record_id='C-NEWS',
             starts_on='2026-11-10', ends_on='2026-12-01'),
        dict(city_documentary, row_type='rate', record_id='R-CITY-01',
             effective_on='2026-11-01', unit_seconds=15, rate_cents=1200),
        dict(city_documentary, row_type='rate', record_id='R-CITY-02',
             effective_on='2026-11-15', unit_seconds=10, rate_cents=1100),
        dict(coast_documentary, row_type='rate', record_id='R-COAST',
             effective_on='2026-11-01', unit_seconds=30, rate_cents=2100),
        dict(city_exhibit, row_type='rate', record_id='R-EXHIBIT',
             effective_on='2026-11-10', unit_seconds=30, rate_cents=900),
        dict(city_news, row_type='rate', record_id='R-NEWS',
             effective_on='2026-11-10', unit_seconds=20, rate_cents=1500),
        dict(city_documentary, row_type='usage', record_id='U-001', contract_id='C-CITY',
             asset='旧城夜班渡轮', used_on='2026-11-01', usage_seconds=16),
        dict(city_documentary, row_type='usage', record_id='U-002', contract_id='C-CITY',
             asset='旧城夜班渡轮', used_on='2026-11-14', usage_seconds=15),
        dict(city_documentary, row_type='usage', record_id='U-003', contract_id='C-CITY',
             asset='旧城夜班渡轮', used_on='2026-11-15', usage_seconds=16),
        dict(coast_documentary, row_type='usage', record_id='U-004', contract_id='C-COAST',
             asset='北堤潮位站', used_on='2026-11-22', usage_seconds=30),
        dict(city_exhibit, row_type='usage', record_id='U-005', contract_id='C-EXHIBIT',
             asset='电车总站旧址', used_on='2026-11-30', usage_seconds=31),
        dict(city_news, row_type='usage', record_id='U-006', contract_id='C-NEWS',
             asset='街坊电影周开幕', used_on='2026-12-01', usage_seconds=10),
    ]
