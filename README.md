# genisolist for CQU Mirror

本仓库将 mirrorz 的 gensiolist 通过 submodule 的模式引入，应该遵循以下命令操作：

- 首次使用：

    ```shell
    git submodule update --init --recursive
    ```

- 在有需要时更新版本：

    ```shell
    git submodule update --recursive --remote
    ```

修改前请先阅读 mirrorz-genisolist 模块的README文件

## 根目录

`genisolist.py`、`version.py` 软链接到 mirrorz-genisolist 下同名文件夹，及时收到更新。

`config.ini` 设置为加载 includes 文件夹下所有 ini 后缀的文件，一般不需要修改

## include
includes 文件夹仍然按照 os、app、font 排列，按需设置。

`includes/font/github` 和 `include/app/github` 用于存储在 GitHub Release 同步的发行版。

与 mirrorz 版本相同未作修改的配置，为了与 mirrorz 同步更新，采用软链接的方式指向 mirrorz-genisolist下同名文件，该文件改名为 `xxx.ref.ini` ，例如：
`includes/os/kali.ref.ini -> mirrorz-genisolist/includes/os/kali.ini`

如需修改，删除 `xxx.ref.ini` 文件，重新创建 `xxx.ini` 并写入配置。

如需禁用配置，修改文件后缀为 `.ini.disabled` 。