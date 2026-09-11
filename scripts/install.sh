#!/bin/sh
# Install the extracted CLI bundle for the current user. No sudo or network access.
set -eu
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
install_dir="${CONNECTNOW_INSTALL_DIR:-$HOME/.local/share/connectnow}"
bin_dir="${CONNECTNOW_BIN_DIR:-$HOME/.local/bin}"
if [ ! -x "$source_dir/connectnow" ] || [ ! -d "$source_dir/_internal" ]; then
  echo '请先解压完整 CLI 安装包，再执行其中的 install.sh。' >&2
  exit 1
fi
if [ -e "$install_dir" ] || [ -L "$install_dir" ]; then
  echo "安装目录已存在：$install_dir；请停止旧服务后选择新目录安装，避免覆盖正在运行的版本。" >&2
  exit 1
fi
mkdir -p "$(dirname -- "$install_dir")" "$bin_dir"
if [ -e "$bin_dir/connectnow" ] || [ -L "$bin_dir/connectnow" ]; then
  echo "$bin_dir/connectnow 已存在，请先核对已有安装。" >&2
  exit 1
fi
cp -R "$source_dir" "$install_dir"
ln -s "$install_dir/connectnow" "$bin_dir/connectnow"
echo "已安装：$bin_dir/connectnow"
echo "启动：\"$bin_dir/connectnow\" start"
echo "若 PATH 中没有 ${bin_dir}，请使用上述完整路径。"
