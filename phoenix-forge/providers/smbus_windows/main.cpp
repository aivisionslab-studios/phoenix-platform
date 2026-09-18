#include "phoenix_smbus_abi.h"
#include <windows.h>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>
#include <iomanip>
#include <cstdlib>

static std::string esc(const std::string&s){std::ostringstream o;for(char c:s){if(c=='\\'||c=='"')o<<'\\'<<c;else o<<c;}return o.str();}
static std::string getstr(const std::string&s,const std::string&k){auto p=s.find("\""+k+"\"");if(p==std::string::npos)return{};p=s.find(':',p);p=s.find('"',p);if(p==std::string::npos)return{};auto e=s.find('"',p+1);return e==std::string::npos?std::string{}:s.substr(p+1,e-p-1);}
static unsigned getuint(const std::string&s,const std::string&k){auto p=s.find("\""+k+"\"");if(p==std::string::npos)return 0;p=s.find(':',p);if(p==std::string::npos)return 0;return static_cast<unsigned>(std::strtoul(s.c_str()+p+1,nullptr,10));}
static HANDLE open_dev(){
    constexpr DWORD kDesiredAccess = 0x80000000UL; // read-only access mask, warning-clean
    constexpr DWORD kShareMode = FILE_SHARE_READ | FILE_SHARE_WRITE;
    constexpr DWORD kFlags = FILE_ATTRIBUTE_NORMAL;
    return CreateFileW(PHOENIX_SMBUS_DEVICE,kDesiredAccess,kShareMode,nullptr,OPEN_EXISTING,kFlags,nullptr);
}
static bool info(HANDLE h,PfSmbusInfoV1&i){DWORD got=0;ZeroMemory(&i,sizeof(i));return DeviceIoControl(h,PFSMBUS_IOCTL_GET_INFO,nullptr,DWORD{0},&i,static_cast<DWORD>(sizeof(i)),&got,nullptr)&&got>=static_cast<DWORD>(sizeof(i))&&i.abi_version==PHOENIX_SMBUS_ABI_VERSION;}
static void handshake(){HANDLE h=open_dev();PfSmbusInfoV1 i{};bool ok=(h!=INVALID_HANDLE_VALUE)&&info(h,i);if(h!=INVALID_HANDLE_VALUE)CloseHandle(h);std::cout<<"{\"schema\":\"phoenix.forge.provider-handshake/v1\",\"name\":\"phoenix-smbus-windows\",\"version\":\"0.21.5.3\",\"privilege\":\"kernel-driver-required\",\"capabilities\":[";bool first=true;if(ok&&(i.capability_bits&PFSMBUS_CAP_ENUMERATE)){std::cout<<"\"spd.enumerate\"";first=false;}if(ok&&(i.capability_bits&PFSMBUS_CAP_READ_SPD)){if(!first)std::cout<<',';std::cout<<"\"spd.read\"";}std::cout<<"],\"driver_status\":\""<<(ok?"READY":"MISSING")<<"\",\"abi_version\":"<<PHOENIX_SMBUS_ABI_VERSION<<"}";}
static void reply(const std::string&id,const std::string&cap,const std::string&st,const std::string&data){std::cout<<"{\"schema\":\"phoenix.forge.provider-response/v1\",\"request_id\":\""<<esc(id)<<"\",\"capability\":\""<<esc(cap)<<"\",\"status\":\""<<st<<"\",\"data\":"<<data<<",\"evidence\":[{\"source\":\"PhoenixForgeSmbus ABI v1\",\"kind\":\"kernel_driver\"}]}";}
static int call(const std::string&cap){
    std::ostringstream ss;ss<<std::cin.rdbuf();auto req=ss.str();auto id=getstr(req,"request_id");
    HANDLE h=open_dev();if(h==INVALID_HANDLE_VALUE){reply(id,cap,"UNAVAILABLE","{\"driver_status\":\"MISSING\"}");return 0;}
    PfSmbusInfoV1 i{};if(!info(h,i)){CloseHandle(h);reply(id,cap,"UNAVAILABLE","{\"driver_status\":\"ABI_MISMATCH\"}");return 0;}

    if(cap=="spd.enumerate"){
        if(!(i.capability_bits&PFSMBUS_CAP_ENUMERATE)){CloseHandle(h);reply(id,cap,"UNAVAILABLE","{\"reason\":\"CAPABILITY_NOT_EXPOSED\"}");return 0;}
        std::vector<std::uint32_t> slots(i.max_slots?i.max_slots:32u);DWORD got=0;
        if(!DeviceIoControl(h,PFSMBUS_IOCTL_ENUMERATE,nullptr,DWORD{0},slots.data(),static_cast<DWORD>(slots.size()*sizeof(std::uint32_t)),&got,nullptr)){
            CloseHandle(h);reply(id,cap,"ERROR","{\"reason\":\"IOCTL_FAILED\"}");return 0;
        }
        std::ostringstream d;d<<"{\"modules\":[";bool first=true;
        for(size_t n=0;n<got/sizeof(std::uint32_t);++n){if(!first)d<<',';first=false;d<<"{\"slot_id\":"<<slots[n]<<"}";}
        d<<"]}";CloseHandle(h);reply(id,cap,"OK",d.str());return 0;
    }

    if(cap=="spd.read"){
        if(!(i.capability_bits&PFSMBUS_CAP_READ_SPD)){CloseHandle(h);reply(id,cap,"UNAVAILABLE","{\"reason\":\"CAPABILITY_NOT_EXPOSED\"}");return 0;}
        unsigned slot=getuint(req,"slot_id");
        PfSmbusReadRequestV1 in{PHOENIX_SMBUS_ABI_VERSION,slot};
        std::vector<unsigned char> buf(i.max_spd_bytes?i.max_spd_bytes:1024u);DWORD got=0;
        if(!DeviceIoControl(h,PFSMBUS_IOCTL_READ_SPD,&in,static_cast<DWORD>(sizeof(in)),buf.data(),static_cast<DWORD>(buf.size()),&got,nullptr)){
            CloseHandle(h);reply(id,cap,"ERROR","{\"reason\":\"IOCTL_FAILED\"}");return 0;
        }
        std::ostringstream hex;hex<<std::hex<<std::setfill('0');
        for(DWORD n=0;n<got;++n)hex<<std::setw(2)<<static_cast<unsigned>(buf[n]);
        std::ostringstream d;d<<"{\"slot_id\":"<<slot<<",\"size_bytes\":"<<got<<",\"spd_hex\":\""<<hex.str()<<"\"}";
        CloseHandle(h);reply(id,cap,"OK",d.str());return 0;
    }

    CloseHandle(h);reply(id,cap,"UNAVAILABLE","{\"reason\":\"NOT_IMPLEMENTED\"}");return 0;
}
int main(int argc,char**argv){
    if(argc>=2&&std::string(argv[1])=="--phoenix-provider-handshake"){handshake();return 0;}
    if(argc>=3&&std::string(argv[1])=="--phoenix-provider-call")return call(argv[2]);
    return 2;
}
