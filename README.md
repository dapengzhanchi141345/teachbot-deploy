# 教学bot 部署包（学校电脑 · 课堂检测 / AI助教 / 12学科网站）

李彦明老师的课堂教学系统：课堂检测出题收卷学情 + AI 助教 + 12 学科网站 + 传统练习系统。
Ubuntu 台式机当服务器（无需 root），学生机同局域网访问。

## 一行命令部署（Hermes 直接执行）

```bash
cd ~ && curl -L -o tb.zip https://codeload.github.com/dapengzhanchi141345/teachbot-deploy/zip/refs/heads/main && python3 -m zipfile -e tb.zip tb/ && cd tb/teachbot-deploy-main && bash run.sh
```

成功标志：终端打印 `教学bot 服务器启动 端口 8377` + `学生/老师打开: http://<IP>:8377/`。

- 用 `python3 -m zipfile` 解压（Ubuntu 桌面机不一定装了 unzip）；仓库更新后重跑同一行即拿新版。
- `bash run.sh` 会自动注册开机自启 + 每 5 分钟看门狗，全程不用 root。

## 启用 AI（可选，30 秒）

本仓库不带 API key（安全考虑）。AI 出题 / AI 助教需要 key：

1. 在部署目录（`tb/teachbot-deploy-main/`）建 `key.txt`，一行粘贴 Agnes API key（`sk-` 开头，来自 Hermes `.env` 的 AGNES_KEY 类变量）；
2. 重跑 `bash run.sh`，看到「✔ 已从 key.txt 补上 AI key」即成。

不补 key 也完全可用：12 学科网站、传统练习系统（718 题）、课堂检测收卷学情均不依赖 AI。

## 各入口

| 用途 | 地址（<IP> = 服务器局域网 IP） |
|---|---|
| 首页导航 | `http://<IP>:8377/` |
| 学生作答（输入题组代码+姓名） | `http://<IP>:8377/quiz/` |
| 教师面板（AI 出题 / 发布 / 实时学情 / CSV 导出） | `http://<IP>:8377/report/` |
| AI 助教聊天 | `http://<IP>:8377/tutor/` |
| 学科网站 | `http://<IP>:8377/sites/<slug>.html`（math/chinese/english/physics/chem/bio/geo/history/morality/it/music/pe） |
| 传统练习系统 | `http://<IP>:8377/classic/<文件名>.html` |

## 教学流程（教师）

1. 开 `/report/` → 选学科/年级/知识点/题量 → **AI 出题**（10~30 秒，检查题目）→ **发布题组** → 得到 6~8 位题组代码；
2. 把入口 `http://<IP>:8377/quiz/` + 代码发给学生；
3. 学生输代码 + 姓名 → 答题 → 自动提交即时出分 + 错题解析；
4. 教师面板「自动刷新(开)」实时看提交人数 / 每题正确率 / 排名，下课前「导出 CSV」。

## 故障速查

| 现象 | 怎么办 |
|---|---|
| 学生打不开 | 重跑 `bash run.sh`（IP 可能变了）；确认同局域网 |
| AI 不出题 | 看 run.sh 有无「△ 未设 AI key」；没有再测外网 |
| 服务挂了 | `pkill -f teachbot.py; bash run.sh`，看 `server.log` |
| 清历史 | 删 `data/sessions.json`（题组）/ `data/submissions.json`（答卷） |

详情见 `使用手册.md`。

李彦明 15684394135
