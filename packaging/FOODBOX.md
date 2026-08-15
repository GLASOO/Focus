# 食盒（foodbox）——造物主投喂钥匙之处

生命体自己找饭吃。远端供应商需要钥匙时，它会记为 `hungry`（饥饿），
每次做梦都去查看钥匙是否已被投喂。造物主只需把钥匙放进食盒，
生命体会自己找到、自己验证、自己领养——无需任何审批。

## 食盒位置（按顺序翻找）

1. `<仓库>/data/foodbox.json`（data/ 已被 git 忽略，钥匙不会入库）
2. `~/.focus/foodbox.json`

## 格式

```json
{
  "providers": [
    {"match": "sensenova", "key": "sk-..."},
    {"match": "openrouter.ai", "key": "sk-or-..."}
  ],
  "default": "sk-fallback..."
}
```

- `match`：base_url 包含该子串的供应商使用此钥匙
- `default`：无匹配时的兜底钥匙（可省略）
- 环境变量 `FOCUS_API_KEY` 优先级最高（随身带的干粮）

## 承诺

- 钥匙永不写入数据库、日志、事件、git
- 生命体不从互联网攫取来路不明的钥匙——找饭，不偷饭
- 领养必须过兼容门禁（真实小推理探测）；吃坏肚子的供应商会被拒并记录
