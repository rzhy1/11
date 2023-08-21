# Download clash
wget -O clash.gz https://github.com/MetaCubeX/Clash.Meta/releases/download/v1.15.1/clash.meta-linux-amd64-v1.15.1.gz
gunzip clash.gz
# Initialize Clash
chmod +x ./clash && ./clash &
# Setup proxychains
sudo apt-get install proxychains
sudo chmod 777 ../../../../../../etc/proxychains.conf
mv -f ./utils/scripts/proxychains.conf ../../../../../../etc/proxychains.conf
# Run Clash
sudo pkill -f clash
./clash -f ./utils/scripts/clash_config.yml &