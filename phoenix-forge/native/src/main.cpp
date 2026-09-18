#ifndef NOMINMAX
#define NOMINMAX
#endif

#include <vulkan/vulkan.h>
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>
#include <fstream>
#include "cpu_bench.hpp"
#ifdef _WIN32
#include <windows.h>
#include <dxgi1_6.h>
#include <intrin.h>
#include <powrprof.h>
#endif

#ifdef min
#undef min
#endif
#ifdef max
#undef max
#endif

static void jsonEscape(const char* s){
    for(;*s;s++){ if(*s=='"'||*s=='\\') std::cout<<'\\'; if((unsigned char)*s>=0x20) std::cout<<*s; }
}
static uint32_t pickType(VkPhysicalDevice pd,uint32_t bits,VkMemoryPropertyFlags required,VkMemoryPropertyFlags preferred=0){
    VkPhysicalDeviceMemoryProperties mp{}; vkGetPhysicalDeviceMemoryProperties(pd,&mp); uint32_t fallback=UINT32_MAX;
    for(uint32_t i=0;i<mp.memoryTypeCount;i++){
        if(!(bits&(1u<<i))) continue; auto f=mp.memoryTypes[i].propertyFlags;
        if((f&required)!=required) continue;
        if(preferred && (f&preferred)==preferred) return i;
        if(fallback==UINT32_MAX) fallback=i;
    }
    if(fallback!=UINT32_MAX) return fallback; throw std::runtime_error("No compatible Vulkan memory type");
}
static uint32_t queueFamily(VkPhysicalDevice pd){
    uint32_t n=0; vkGetPhysicalDeviceQueueFamilyProperties(pd,&n,nullptr); std::vector<VkQueueFamilyProperties> q(n); vkGetPhysicalDeviceQueueFamilyProperties(pd,&n,q.data());
    for(uint32_t i=0;i<n;i++) if(q[i].queueFlags&VK_QUEUE_TRANSFER_BIT) return i;
    for(uint32_t i=0;i<n;i++) if(q[i].queueFlags&VK_QUEUE_COMPUTE_BIT) return i;
    return 0;
}
struct Ctx{VkInstance inst{};VkPhysicalDevice pd{};VkDevice dev{};VkQueue q{};uint32_t qfi{};VkCommandPool pool{};VkPhysicalDeviceProperties prop{};};
static Ctx createCtx(uint32_t deviceIndex=0){
    Ctx c{}; VkApplicationInfo ai{VK_STRUCTURE_TYPE_APPLICATION_INFO}; ai.pApplicationName="Phoenix Forge Native"; ai.apiVersion=VK_API_VERSION_1_1;
    VkInstanceCreateInfo ici{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO}; ici.pApplicationInfo=&ai; if(vkCreateInstance(&ici,nullptr,&c.inst)!=VK_SUCCESS) throw std::runtime_error("vkCreateInstance failed");
    uint32_t n=0; vkEnumeratePhysicalDevices(c.inst,&n,nullptr); if(!n) throw std::runtime_error("no Vulkan device"); std::vector<VkPhysicalDevice>d(n); vkEnumeratePhysicalDevices(c.inst,&n,d.data()); if(deviceIndex>=n) throw std::runtime_error("device index out of range"); c.pd=d[deviceIndex]; vkGetPhysicalDeviceProperties(c.pd,&c.prop); c.qfi=queueFamily(c.pd);
    float prio=1.f; VkDeviceQueueCreateInfo qci{VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO}; qci.queueFamilyIndex=c.qfi; qci.queueCount=1; qci.pQueuePriorities=&prio; VkDeviceCreateInfo dci{VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO}; dci.queueCreateInfoCount=1; dci.pQueueCreateInfos=&qci; if(vkCreateDevice(c.pd,&dci,nullptr,&c.dev)!=VK_SUCCESS) throw std::runtime_error("vkCreateDevice failed"); vkGetDeviceQueue(c.dev,c.qfi,0,&c.q);
    VkCommandPoolCreateInfo pci{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO}; pci.queueFamilyIndex=c.qfi; pci.flags=VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT; if(vkCreateCommandPool(c.dev,&pci,nullptr,&c.pool)!=VK_SUCCESS) throw std::runtime_error("vkCreateCommandPool failed"); return c;
}
static void destroyCtx(Ctx &c){if(c.dev)vkDeviceWaitIdle(c.dev);if(c.pool)vkDestroyCommandPool(c.dev,c.pool,nullptr);if(c.dev)vkDestroyDevice(c.dev,nullptr);if(c.inst)vkDestroyInstance(c.inst,nullptr);}
struct Buf{VkBuffer b{};VkDeviceMemory m{};VkDeviceSize size{};uint32_t type{};};
static Buf makeBuffer(Ctx&c,VkDeviceSize sz,VkBufferUsageFlags usage,VkMemoryPropertyFlags req,VkMemoryPropertyFlags pref=0){
    Buf x{};x.size=sz;VkBufferCreateInfo bi{VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO};bi.size=sz;bi.usage=usage;bi.sharingMode=VK_SHARING_MODE_EXCLUSIVE;if(vkCreateBuffer(c.dev,&bi,nullptr,&x.b)!=VK_SUCCESS)throw std::runtime_error("vkCreateBuffer failed");VkMemoryRequirements mr{};vkGetBufferMemoryRequirements(c.dev,x.b,&mr);x.type=pickType(c.pd,mr.memoryTypeBits,req,pref);VkMemoryAllocateInfo mai{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};mai.allocationSize=mr.size;mai.memoryTypeIndex=x.type;if(vkAllocateMemory(c.dev,&mai,nullptr,&x.m)!=VK_SUCCESS){vkDestroyBuffer(c.dev,x.b,nullptr);throw std::runtime_error("vkAllocateMemory failed");}if(vkBindBufferMemory(c.dev,x.b,x.m,0)!=VK_SUCCESS)throw std::runtime_error("vkBindBufferMemory failed");return x;
}
static void destroyBuffer(Ctx&c,Buf &x){if(x.b)vkDestroyBuffer(c.dev,x.b,nullptr);if(x.m)vkFreeMemory(c.dev,x.m,nullptr);x={};}
static void fillCopyRange(Ctx&c,Buf&device,VkDeviceSize devOffset,Buf&stage,VkDeviceSize bytes,uint32_t pattern){
    VkCommandBufferAllocateInfo ai{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};ai.commandPool=c.pool;ai.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY;ai.commandBufferCount=1;VkCommandBuffer cb{};if(vkAllocateCommandBuffers(c.dev,&ai,&cb)!=VK_SUCCESS)throw std::runtime_error("vkAllocateCommandBuffers failed");
    VkCommandBufferBeginInfo bi{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};bi.flags=VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;vkBeginCommandBuffer(cb,&bi);vkCmdFillBuffer(cb,device.b,devOffset,bytes,pattern);
    VkBufferMemoryBarrier barrier{VK_STRUCTURE_TYPE_BUFFER_MEMORY_BARRIER};barrier.srcAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT;barrier.dstAccessMask=VK_ACCESS_TRANSFER_READ_BIT;barrier.srcQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED;barrier.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED;barrier.buffer=device.b;barrier.offset=devOffset;barrier.size=bytes;vkCmdPipelineBarrier(cb,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_PIPELINE_STAGE_TRANSFER_BIT,0,0,nullptr,1,&barrier,0,nullptr);
    VkBufferCopy cp{devOffset,0,bytes};vkCmdCopyBuffer(cb,device.b,stage.b,1,&cp);vkEndCommandBuffer(cb);VkSubmitInfo si{VK_STRUCTURE_TYPE_SUBMIT_INFO};si.commandBufferCount=1;si.pCommandBuffers=&cb;if(vkQueueSubmit(c.q,1,&si,VK_NULL_HANDLE)!=VK_SUCCESS)throw std::runtime_error("vkQueueSubmit failed");vkQueueWaitIdle(c.q);vkFreeCommandBuffers(c.dev,c.pool,1,&cb);
}
static void copyRange(Ctx&c,Buf&source,VkDeviceSize sourceOffset,Buf&destination,VkDeviceSize bytes){
    VkCommandBufferAllocateInfo ai{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};ai.commandPool=c.pool;ai.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY;ai.commandBufferCount=1;VkCommandBuffer cb{};if(vkAllocateCommandBuffers(c.dev,&ai,&cb)!=VK_SUCCESS)throw std::runtime_error("vkAllocateCommandBuffers failed");VkCommandBufferBeginInfo bi{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};bi.flags=VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;vkBeginCommandBuffer(cb,&bi);VkBufferCopy cp{sourceOffset,0,bytes};vkCmdCopyBuffer(cb,source.b,destination.b,1,&cp);vkEndCommandBuffer(cb);VkSubmitInfo si{VK_STRUCTURE_TYPE_SUBMIT_INFO};si.commandBufferCount=1;si.pCommandBuffers=&cb;if(vkQueueSubmit(c.q,1,&si,VK_NULL_HANDLE)!=VK_SUCCESS)throw std::runtime_error("vkQueueSubmit copy failed");if(vkQueueWaitIdle(c.q)!=VK_SUCCESS)throw std::runtime_error("vkQueueWaitIdle copy failed");vkFreeCommandBuffers(c.dev,c.pool,1,&cb);
}
struct ErrorDetail{
    uint64_t window{}; int pass{}; uint32_t patternIndex{}; uint32_t expected{}; uint32_t actual{};
    uint64_t wordInWindow{}; uint64_t logicalWord{};
};
static uint64_t verifyStage(Ctx&c,Buf&stage,VkDeviceSize bytes,uint32_t pattern,bool fullScan,
    uint64_t &checked,uint64_t &uniqueChecked,uint64_t logicalBaseWord,uint64_t windowIndex,
    int pass,uint32_t patternIndex,uint64_t maxDetails,std::vector<ErrorDetail>&details){
    void* ptr=nullptr;
    if(vkMapMemory(c.dev,stage.m,0,bytes,0,&ptr)!=VK_SUCCESS)throw std::runtime_error("vkMapMemory staging failed");
    auto *words=(uint32_t*)ptr; size_t n=(size_t)(bytes/4); size_t step=fullScan?1:std::max<size_t>(1,n/1048576);
    uint64_t errors=0; checked=0; uniqueChecked=0;
    for(size_t i=0;i<n;i+=step){
        checked++; uniqueChecked++;
        if(words[i]!=pattern){
            errors++;
            if(details.size()<maxDetails)details.push_back(ErrorDetail{windowIndex,pass,patternIndex,pattern,words[i],(uint64_t)i,logicalBaseWord+(uint64_t)i});
        }
    }
    vkUnmapMemory(c.dev,stage.m); return errors;
}
static void printErrorDetails(const std::vector<ErrorDetail>&details){
    std::cout<<"\"error_details\":[";
    for(size_t i=0;i<details.size();i++){
        const auto&e=details[i]; if(i)std::cout<<","; uint32_t diff=e.expected^e.actual;
        std::cout<<"{\"window_index\":"<<e.window<<",\"pass\":"<<(e.pass+1)<<",\"pattern_index\":"<<(e.patternIndex+1)
            <<",\"pattern_name\":\"constant_0x"<<std::hex<<std::uppercase<<e.expected<<std::dec<<"\",\"expected\":"<<e.expected
            <<",\"expected_hex\":\"0x"<<std::hex<<std::uppercase<<e.expected<<"\",\"actual\":"<<std::dec<<e.actual
            <<",\"actual_hex\":\"0x"<<std::hex<<std::uppercase<<e.actual<<"\",\"xor_mask_hex\":\"0x"<<diff<<std::dec
            <<"\",\"word_in_window\":"<<e.wordInWindow<<",\"byte_offset_in_window\":"<<(e.wordInWindow*4)
            <<",\"logical_word\":"<<e.logicalWord<<",\"logical_byte_offset\":"<<(e.logicalWord*4)<<",\"differing_bits\":[";
        bool first=true; for(uint32_t bit=0;bit<32;bit++)if(diff&(1u<<bit)){if(!first)std::cout<<",";first=false;std::cout<<bit;}
        std::cout<<"]}";
    }
    std::cout<<"]";
}
static uint64_t primaryLocalHeap(Ctx&c){VkPhysicalDeviceMemoryProperties mp{};vkGetPhysicalDeviceMemoryProperties(c.pd,&mp);uint64_t best=0;for(uint32_t i=0;i<mp.memoryHeapCount;i++)if(mp.memoryHeaps[i].flags&VK_MEMORY_HEAP_DEVICE_LOCAL_BIT)best=std::max<uint64_t>(best,mp.memoryHeaps[i].size);return best;}
static int doDetect(Ctx&c){
    VkPhysicalDeviceMemoryProperties mp{};vkGetPhysicalDeviceMemoryProperties(c.pd,&mp);uint32_t qn=0;vkGetPhysicalDeviceQueueFamilyProperties(c.pd,&qn,nullptr);std::vector<VkQueueFamilyProperties> qs(qn);vkGetPhysicalDeviceQueueFamilyProperties(c.pd,&qn,qs.data());
    std::cout<<"{\"passed\":true,\"provider\":\"Vulkan\",\"device_name\":\"";jsonEscape(c.prop.deviceName);std::cout<<"\",\"device_type\":"<<c.prop.deviceType<<",\"vendor_id\":"<<c.prop.vendorID<<",\"vendor_id_hex\":\"0x"<<std::hex<<std::uppercase<<c.prop.vendorID<<std::dec<<"\",\"device_id\":"<<c.prop.deviceID<<",\"device_id_hex\":\"0x"<<std::hex<<std::uppercase<<c.prop.deviceID<<std::dec<<"\",\"api_version\":"<<c.prop.apiVersion<<",\"driver_version\":"<<c.prop.driverVersion<<",\"limits\":{\"max_compute_workgroup_invocations\":"<<c.prop.limits.maxComputeWorkGroupInvocations<<",\"max_compute_workgroup_count\":["<<c.prop.limits.maxComputeWorkGroupCount[0]<<","<<c.prop.limits.maxComputeWorkGroupCount[1]<<","<<c.prop.limits.maxComputeWorkGroupCount[2]<<"],\"max_storage_buffer_range\":"<<c.prop.limits.maxStorageBufferRange<<",\"max_memory_allocation_count\":"<<c.prop.limits.maxMemoryAllocationCount<<"},\"memory_heaps\":[";
    for(uint32_t i=0;i<mp.memoryHeapCount;i++){if(i)std::cout<<",";std::cout<<"{\"index\":"<<i<<",\"size_bytes\":"<<(uint64_t)mp.memoryHeaps[i].size<<",\"device_local\":"<<((mp.memoryHeaps[i].flags&VK_MEMORY_HEAP_DEVICE_LOCAL_BIT)?"true":"false")<<"}";}std::cout<<"],\"memory_types\":[";for(uint32_t i=0;i<mp.memoryTypeCount;i++){if(i)std::cout<<",";std::cout<<"{\"index\":"<<i<<",\"heap_index\":"<<mp.memoryTypes[i].heapIndex<<",\"property_flags\":"<<mp.memoryTypes[i].propertyFlags<<"}";}std::cout<<"],\"queue_families\":[";for(uint32_t i=0;i<qn;i++){if(i)std::cout<<",";std::cout<<"{\"index\":"<<i<<",\"queue_count\":"<<qs[i].queueCount<<",\"flags\":"<<qs[i].queueFlags<<",\"timestamp_valid_bits\":"<<qs[i].timestampValidBits<<"}";}std::cout<<"]}\n";return 0;
}
static int doVram(Ctx&c,uint64_t mb,int passes,bool fullScan,bool continueOnError,uint64_t maxDetails){
    VkDeviceSize sz=mb*1024ull*1024ull;sz=(sz/4)*4;Buf devbuf{},stage{};uint64_t errors=0,checked=0;auto st=std::chrono::steady_clock::now();
    try{
        devbuf=makeBuffer(c,sz,VK_BUFFER_USAGE_TRANSFER_SRC_BIT|VK_BUFFER_USAGE_TRANSFER_DST_BIT,VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
        stage=makeBuffer(c,sz,VK_BUFFER_USAGE_TRANSFER_DST_BIT,VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT,VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
        const uint32_t pats[]={0x00000000u,0xFFFFFFFFu,0xAAAAAAAAu,0x55555555u,0x33333333u,0xCCCCCCCCu,0xA5A5A5A5u,0x5A5A5A5Au};
        std::vector<ErrorDetail> details; uint64_t uniqueChecked=0;
        for(int p=0;p<passes&&(continueOnError||errors==0);p++)for(uint32_t pi=0;pi<8;pi++){std::cerr<<"progress pass="<<(p+1)<<"/"<<passes<<" pattern="<<(pi+1)<<"/8\n";fillCopyRange(c,devbuf,0,stage,sz,pats[pi]);uint64_t ckd=0,uniq=0;uint64_t found=verifyStage(c,stage,sz,pats[pi],fullScan,ckd,uniq,0,0,p,pi,maxDetails,details);errors+=found;checked+=ckd;if(p==0&&pi==0)uniqueChecked=uniq;if(found&&!continueOnError)break;}
        auto sec=std::chrono::duration<double>(std::chrono::steady_clock::now()-st).count();double gb=(double)sz/1e9;double effective=(sec>0? (gb*2.0*passes*8.0)/sec:0.0);double coverage=(sz?100.0*(double)uniqueChecked/(double)(sz/4):0.0);destroyBuffer(c,stage);destroyBuffer(c,devbuf);
        std::cout<<"{\"passed\":"<<(errors==0?"true":"false")<<",\"status\":\""<<(errors?"MEMORY_ERROR":(fullScan?"FULL_SCAN_PASS":"QUICK_PASS"))<<"\",\"device_name\":\"";jsonEscape(c.prop.deviceName);std::cout<<"\",\"requested_mb\":"<<mb<<",\"passes\":"<<passes<<",\"device_local\":true,\"patterns\":8,\"checked_words\":"<<checked<<",\"unique_words_per_pattern\":"<<uniqueChecked<<",\"address_coverage_percent\":"<<coverage<<",\"sample_errors\":"<<errors<<",\"error_details_truncated\":"<<((errors>details.size())?"true":"false")<<",\"full_scan\":"<<(fullScan?"true":"false")<<",\"continue_on_error\":"<<(continueOnError?"true":"false")<<",\"duration_s\":"<<sec<<",\"validation_throughput_gbps\":"<<effective<<",";printErrorDetails(details);std::cout<<"}\n";return errors?8:0;
    }catch(const std::exception&e){if(stage.b)destroyBuffer(c,stage);if(devbuf.b)destroyBuffer(c,devbuf);std::cout<<"{\"passed\":false,\"error\":\"";jsonEscape(e.what());std::cout<<"\",\"requested_mb\":"<<mb<<"}\n";return 7;}
}
static int doVramMap(Ctx&c,uint64_t chunkMb,uint64_t targetMb,int passes,bool fullScan,bool adaptive,uint64_t minChunkMb,uint64_t reserveMb,bool continueOnError,uint64_t maxDetails){
    uint64_t heap=primaryLocalHeap(c), heapMb=heap/(1024ull*1024ull);
    chunkMb=std::max<uint64_t>(16,chunkMb); minChunkMb=std::max<uint64_t>(16,std::min<uint64_t>(minChunkMb,chunkMb)); reserveMb=std::min<uint64_t>(reserveMb,heapMb);
    if(targetMb==0){
        uint64_t autoTarget=heapMb>reserveMb?heapMb-reserveMb:chunkMb;
        targetMb=(autoTarget/chunkMb)*chunkMb;
        targetMb=std::max<uint64_t>(chunkMb,targetMb);
    }
    targetMb=std::min<uint64_t>(targetMb,heapMb);
    const uint32_t pats[]={0x00000000u,0xFFFFFFFFu,0xAAAAAAAAu,0x55555555u,0x33333333u,0xCCCCCCCCu,0xA5A5A5A5u,0x5A5A5A5Au};
    struct Region{Buf buf{};uint64_t startMb{};uint64_t sizeMb{};uint64_t errors{};uint64_t checked{};uint64_t uniqueChecked{};double sec{};};
    std::vector<Region> regions; regions.reserve((size_t)(targetMb/std::max<uint64_t>(1,minChunkMb)+2));
    uint64_t allocatedMb=0,attemptChunk=chunkMb; auto st=std::chrono::steady_clock::now(); std::string allocationError;

    while(allocatedMb<targetMb){
        uint64_t remaining=targetMb-allocatedMb;
        uint64_t thisMb=std::min<uint64_t>(attemptChunk,remaining);
        if(thisMb<minChunkMb && remaining>=minChunkMb)thisMb=minChunkMb;
        if(thisMb==0)break;
        try{
            Region r{}; r.startMb=allocatedMb; r.sizeMb=thisMb;
            r.buf=makeBuffer(c,thisMb*1024ull*1024ull,VK_BUFFER_USAGE_TRANSFER_SRC_BIT|VK_BUFFER_USAGE_TRANSFER_DST_BIT,VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
            regions.push_back(std::move(r)); allocatedMb+=thisMb;
            std::cerr<<"allocation resident_mb="<<allocatedMb<<"/"<<targetMb<<" chunk_mb="<<thisMb<<"\n";
        }catch(const std::exception&e){
            allocationError=e.what();
            if(adaptive && attemptChunk>minChunkMb){
                uint64_t next=std::max<uint64_t>(minChunkMb,attemptChunk/2);
                if(next==attemptChunk)break;
                attemptChunk=next;
                std::cerr<<"allocation fallback chunk_mb="<<attemptChunk<<" reason="<<allocationError<<"\n";
                continue;
            }
            break;
        }
    }

    if(regions.empty()){
        std::cout<<"{\"passed\":false,\"status\":\"ALLOCATION_FAILED\",\"error\":\"";jsonEscape(allocationError.empty()?"no resident VRAM allocation could be created":allocationError.c_str());std::cout<<"\",\"target_mb\":"<<targetMb<<",\"allocated_mb\":0,\"chunk_mb\":"<<chunkMb<<",\"adaptive\":"<<(adaptive?"true":"false")<<"}\n";
        return 7;
    }

    uint64_t largest=0; for(const auto&r:regions)largest=std::max<uint64_t>(largest,r.sizeMb);
    Buf stage{};
    try{stage=makeBuffer(c,largest*1024ull*1024ull,VK_BUFFER_USAGE_TRANSFER_DST_BIT,VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT,VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);}catch(const std::exception&e){for(auto&r:regions)destroyBuffer(c,r.buf);std::cout<<"{\"passed\":false,\"status\":\"ALLOCATION_FAILED\",\"error\":\"";jsonEscape(e.what());std::cout<<"\",\"target_mb\":"<<targetMb<<",\"allocated_mb\":"<<allocatedMb<<"}\n";return 7;}

    uint64_t totalErr=0,totalChecked=0,totalUnique=0,validatedMb=0;std::vector<ErrorDetail> details;
    for(size_t w=0;w<regions.size();w++){
        Region&r=regions[w];auto ws=std::chrono::steady_clock::now();uint64_t ecount=0,ccount=0;VkDeviceSize bytes=r.sizeMb*1024ull*1024ull;
        for(int p=0;p<passes&&(continueOnError||ecount==0);p++)for(uint32_t pi=0;pi<8;pi++){
            std::cerr<<"progress window="<<(w+1)<<"/"<<regions.size()<<" logical_mb="<<r.startMb<<"-"<<(r.startMb+r.sizeMb)<<" pass="<<(p+1)<<"/"<<passes<<" pattern="<<(pi+1)<<"/8\n";
            fillCopyRange(c,r.buf,0,stage,bytes,pats[pi]);uint64_t ckd=0,uniq=0;uint64_t found=verifyStage(c,stage,bytes,pats[pi],fullScan,ckd,uniq,(r.startMb*1024ull*1024ull)/4,w,p,pi,maxDetails,details);ecount+=found;ccount+=ckd;if(p==0&&pi==0)r.uniqueChecked=uniq;if(found&&!continueOnError)break;
        }
        r.errors=ecount;r.checked=ccount;r.sec=std::chrono::duration<double>(std::chrono::steady_clock::now()-ws).count();totalErr+=ecount;totalChecked+=ccount;totalUnique+=r.uniqueChecked;if(ecount==0)validatedMb+=r.sizeMb;
    }
    double totalSec=std::chrono::duration<double>(std::chrono::steady_clock::now()-st).count();destroyBuffer(c,stage);for(auto&r:regions)destroyBuffer(c,r.buf);
    std::string status=totalErr?"MEMORY_ERROR":(allocatedMb<targetMb?"BUDGET_EXHAUSTED":(fullScan?"FULL_SCAN_PASS":"QUICK_PASS"));bool ok=status=="FULL_SCAN_PASS"||status=="QUICK_PASS";
    uint64_t residentWords=(allocatedMb*1024ull*1024ull)/4;double coverage=residentWords?100.0*(double)totalUnique/(double)residentWords:0.0;
    std::cout<<"{\"passed\":"<<(ok?"true":"false")<<",\"status\":\""<<status<<"\",\"health_assessment\":\""<<(totalErr?"SUSPECTED_UNSTABLE":(fullScan?"INCONCLUSIVE_NEEDS_REPEAT":"INCONCLUSIVE_QUICK_TEST"))<<"\",\"device_name\":\"";jsonEscape(c.prop.deviceName);std::cout<<"\",\"allocation_mode\":\"multi_allocation_resident\",\"target_mb\":"<<targetMb<<",\"allocated_mb\":"<<allocatedMb<<",\"validated_mb\":"<<validatedMb<<",\"heap_mb\":"<<heapMb<<",\"reserve_mb\":"<<reserveMb<<",\"chunk_mb_requested\":"<<chunkMb<<",\"min_chunk_mb\":"<<minChunkMb<<",\"adaptive\":"<<(adaptive?"true":"false")<<",\"passes\":"<<passes<<",\"patterns\":8,\"full_scan\":"<<(fullScan?"true":"false")<<",\"continue_on_error\":"<<(continueOnError?"true":"false")<<",\"address_coverage_percent\":"<<coverage<<",\"physical_address_map\":false,\"mapping_note\":\"Logical windows across multiple resident Vulkan device-local allocations; physical GDDR placement is driver-managed and not exposed by Vulkan.\",\"total_checked_words\":"<<totalChecked<<",\"unique_words_per_pattern\":"<<totalUnique<<",\"sample_errors\":"<<totalErr<<",\"error_details_truncated\":"<<((totalErr>details.size())?"true":"false")<<",\"duration_s\":"<<totalSec<<",\"windows\":[";
    for(size_t w=0;w<regions.size();w++){auto&r=regions[w];double wc=(r.sizeMb?100.0*(double)r.uniqueChecked/(double)((r.sizeMb*1024ull*1024ull)/4):0.0);if(w)std::cout<<",";std::cout<<"{\"index\":"<<w<<",\"start_mb\":"<<r.startMb<<",\"end_mb\":"<<(r.startMb+r.sizeMb)<<",\"size_mb\":"<<r.sizeMb<<",\"passed\":"<<(r.errors==0?"true":"false")<<",\"errors\":"<<r.errors<<",\"checked_words\":"<<r.checked<<",\"unique_words_per_pattern\":"<<r.uniqueChecked<<",\"address_coverage_percent\":"<<wc<<",\"duration_s\":"<<r.sec<<"}";}std::cout<<"],";printErrorDetails(details);
    if(allocatedMb<targetMb){std::cout<<",\"allocation_error\":\"";jsonEscape(allocationError.empty()?"resident allocation target could not be reached":allocationError.c_str());std::cout<<"\"";}std::cout<<"}\n";return totalErr?8:(allocatedMb<targetMb?10:0);
}
static int doGpuStress(Ctx&c,uint64_t mb,int seconds){
    VkDeviceSize sz=mb*1024ull*1024ull;sz=(sz/4)*4;Buf devbuf{},stage{};uint64_t iterations=0;auto start=std::chrono::steady_clock::now();
    try{devbuf=makeBuffer(c,sz,VK_BUFFER_USAGE_TRANSFER_SRC_BIT|VK_BUFFER_USAGE_TRANSFER_DST_BIT,VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);stage=makeBuffer(c,sz,VK_BUFFER_USAGE_TRANSFER_DST_BIT,VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT,VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);while(std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count()<seconds){fillCopyRange(c,devbuf,0,stage,sz,(iterations&1)?0xAAAAAAAAu:0x55555555u);iterations++;}}
    catch(const std::exception&e){if(stage.b)destroyBuffer(c,stage);if(devbuf.b)destroyBuffer(c,devbuf);std::cout<<"{\"passed\":false,\"error\":\"";jsonEscape(e.what());std::cout<<"\"}\n";return 9;}
    double sec=std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();double gb=(double)sz/1e9;double traffic=gb*2.0*iterations;destroyBuffer(c,stage);destroyBuffer(c,devbuf);std::cout<<"{\"passed\":true,\"device_name\":\"";jsonEscape(c.prop.deviceName);std::cout<<"\",\"requested_mb\":"<<mb<<",\"iterations\":"<<iterations<<",\"duration_s\":"<<sec<<",\"approx_transfer_gbps\":"<<(sec?traffic/sec:0)<<"}\n";return 0;
}

static int doVramBandwidth(Ctx&c,uint64_t mb,int seconds){
    VkDeviceSize sz=(mb*1024ull*1024ull/4)*4;Buf source{},destination{},stage{};uint64_t copies=0;const uint32_t pattern=0xA5A5A5A5u;
    auto started=std::chrono::steady_clock::now();
    try{
        source=makeBuffer(c,sz,VK_BUFFER_USAGE_TRANSFER_SRC_BIT|VK_BUFFER_USAGE_TRANSFER_DST_BIT,VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
        destination=makeBuffer(c,sz,VK_BUFFER_USAGE_TRANSFER_SRC_BIT|VK_BUFFER_USAGE_TRANSFER_DST_BIT,VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
        stage=makeBuffer(c,sz,VK_BUFFER_USAGE_TRANSFER_DST_BIT,VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT,VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
        fillCopyRange(c,source,0,stage,sz,pattern);
        while(std::chrono::duration<double>(std::chrono::steady_clock::now()-started).count()<seconds){
            VkCommandBufferAllocateInfo ai{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};ai.commandPool=c.pool;ai.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY;ai.commandBufferCount=1;VkCommandBuffer cb{};vkAllocateCommandBuffers(c.dev,&ai,&cb);VkCommandBufferBeginInfo bi{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};bi.flags=VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;vkBeginCommandBuffer(cb,&bi);VkBufferCopy cp{0,0,sz};vkCmdCopyBuffer(cb,source.b,destination.b,1,&cp);vkEndCommandBuffer(cb);VkSubmitInfo si{VK_STRUCTURE_TYPE_SUBMIT_INFO};si.commandBufferCount=1;si.pCommandBuffers=&cb;if(vkQueueSubmit(c.q,1,&si,VK_NULL_HANDLE)!=VK_SUCCESS)throw std::runtime_error("vkQueueSubmit bandwidth failed");if(vkQueueWaitIdle(c.q)!=VK_SUCCESS)throw std::runtime_error("vkQueueWaitIdle bandwidth failed");vkFreeCommandBuffers(c.dev,c.pool,1,&cb);std::swap(source,destination);++copies;
        }
        copyRange(c,source,0,stage,sz);uint64_t checked=0,unique=0;std::vector<ErrorDetail>details;uint64_t errors=verifyStage(c,stage,sz,pattern,true,checked,unique,0,0,0,0,16,details);double elapsed=std::chrono::duration<double>(std::chrono::steady_clock::now()-started).count();double gbps=elapsed?double(sz)*copies/1e9/elapsed:0;destroyBuffer(c,stage);destroyBuffer(c,destination);destroyBuffer(c,source);std::cout<<"{\"passed\":"<<(errors==0?"true":"false")<<",\"status\":\""<<(errors?"DATA_MISMATCH":"PASS")<<"\",\"mode\":\"vulkan_device_to_device\",\"device_name\":\"";jsonEscape(c.prop.deviceName);std::cout<<"\",\"size_mb\":"<<mb<<",\"copies\":"<<copies<<",\"duration_s\":"<<elapsed<<",\"bandwidth_gbps\":"<<gbps<<",\"checked_words\":"<<checked<<",\"errors\":"<<errors<<",\"correctness_verified\":"<<(errors==0?"true":"false")<<"}\n";return errors?8:0;
    }catch(const std::exception&e){if(stage.b)destroyBuffer(c,stage);if(destination.b)destroyBuffer(c,destination);if(source.b)destroyBuffer(c,source);std::cout<<"{\"passed\":false,\"status\":\"NATIVE_ERROR\",\"error\":\"";jsonEscape(e.what());std::cout<<"\"}\n";return 23;}
}

#ifdef _WIN32
static int doDxgiInfo(){
    IDXGIFactory1* factory=nullptr;
    HRESULT hr=CreateDXGIFactory1(__uuidof(IDXGIFactory1),(void**)&factory);
    if(FAILED(hr)||!factory){std::cout<<"{\"passed\":false,\"error\":\"CreateDXGIFactory1 failed\"}\n";return 11;}
    std::cout<<"{\"passed\":true,\"provider\":\"DXGI\",\"adapters\":[";
    bool first=true;
    for(UINT i=0;;++i){IDXGIAdapter1* a=nullptr;if(factory->EnumAdapters1(i,&a)==DXGI_ERROR_NOT_FOUND)break;if(!a)continue;DXGI_ADAPTER_DESC1 d{};a->GetDesc1(&d);
        if(!first)std::cout<<",";first=false;
        char name[512]{};WideCharToMultiByte(CP_UTF8,0,d.Description,-1,name,sizeof(name),nullptr,nullptr);
        std::cout<<"{\"index\":"<<i<<",\"name\":\"";jsonEscape(name);std::cout<<"\",\"vendor_id\":"<<d.VendorId<<",\"device_id\":"<<d.DeviceId<<",\"subsys_id\":"<<d.SubSysId<<",\"revision\":"<<d.Revision<<",\"dedicated_video_memory_bytes\":"<<(uint64_t)d.DedicatedVideoMemory<<",\"dedicated_system_memory_bytes\":"<<(uint64_t)d.DedicatedSystemMemory<<",\"shared_system_memory_bytes\":"<<(uint64_t)d.SharedSystemMemory<<",\"luid_low\":"<<d.AdapterLuid.LowPart<<",\"luid_high\":"<<d.AdapterLuid.HighPart<<"}";
        a->Release();
    }
    std::cout<<"]}\n";factory->Release();return 0;
}
static int doCpuInfo(){
    int r[4]{};__cpuid(r,0);int maxLeaf=r[0];char vendor[13]{};memcpy(vendor,&r[1],4);memcpy(vendor+4,&r[3],4);memcpy(vendor+8,&r[2],4);__cpuid(r,0x80000000);unsigned maxExt=(unsigned)r[0];char brand[49]{};if(maxExt>=0x80000004)for(int i=0;i<3;i++){__cpuid(r,0x80000002+i);memcpy(brand+i*16,r,16);}
    __cpuid(r,1);bool sse2=(r[3]&(1<<26))!=0;bool avx=(r[2]&(1<<28))!=0;bool osxsave=(r[2]&(1<<27))!=0;bool avx2=false;
    unsigned sig=(unsigned)r[0],bf=(sig>>8)&15,bm=(sig>>4)&15,ef=(sig>>20)&255,em=(sig>>16)&15;unsigned family=bf==15?bf+ef:bf,model=(bf==6||bf==15)?(em<<4)+bm:bm,stepping=sig&15;
    if(maxLeaf>=7){__cpuidex(r,7,0);avx2=(r[1]&(1<<5))!=0;}
    std::cout<<"{\"passed\":true,\"provider\":\"CPUID\",\"vendor\":\"";jsonEscape(vendor);std::cout<<"\",\"brand\":\"";jsonEscape(brand);std::cout<<"\",\"max_basic_leaf\":"<<maxLeaf<<",\"max_extended_leaf\":"<<maxExt<<",\"family\":"<<family<<",\"model\":"<<model<<",\"stepping\":"<<stepping<<",\"sse2\":"<<(sse2?"true":"false")<<",\"avx\":"<<(avx?"true":"false")<<",\"osxsave\":"<<(osxsave?"true":"false")<<",\"avx2\":"<<(avx2?"true":"false")<<"}\n";return 0;
}
static void jsonBoolField(const char* name,bool value,bool &first){if(!first)std::cout<<",";first=false;std::cout<<"\""<<name<<"\":"<<(value?"true":"false");}

static int doCpuClockInfo(unsigned samples,unsigned intervalMs){
    samples=(std::max)(1u,(std::min)(samples,120u));
    intervalMs=(std::max)(10u,(std::min)(intervalMs,5000u));
    DWORD groups=GetActiveProcessorGroupCount();
    DWORD logical=GetActiveProcessorCount(ALL_PROCESSOR_GROUPS);
    if(logical==0){std::cout<<"{\"passed\":false,\"error\":\"GetActiveProcessorCount returned zero\"}\n";return 14;}
    struct PhoenixProcessorPowerInformation { ULONG Number; ULONG MaxMhz; ULONG CurrentMhz; ULONG MhzLimit; ULONG MaxIdleState; ULONG CurrentIdleState; };
    std::vector<PhoenixProcessorPowerInformation> info(logical);
    struct Agg{uint64_t sum{};uint32_t min{UINT32_MAX};uint32_t max{};uint32_t maxMhz{};uint32_t limitMhz{};uint64_t seen{};};
    std::vector<Agg> agg(logical);
    uint64_t totalSamples=0;
    for(unsigned sample=0;sample<samples;sample++){
        ULONG outSize=(ULONG)(info.size()*sizeof(PhoenixProcessorPowerInformation));
        LONG st=(LONG)CallNtPowerInformation(ProcessorInformation,nullptr,0,info.data(),outSize);
        if(st!=0){std::cout<<"{\"passed\":false,\"provider\":\"CallNtPowerInformation\",\"ntstatus\":"<<(long)st<<",\"error\":\"ProcessorInformation query failed\"}\n";return 15;}
        for(size_t i=0;i<info.size();i++){
            auto &a=agg[i];auto &x=info[i];
            a.sum+=x.CurrentMhz;a.min=(std::min)(a.min,(uint32_t)x.CurrentMhz);a.max=(std::max)(a.max,(uint32_t)x.CurrentMhz);a.maxMhz=(std::max)(a.maxMhz,(uint32_t)x.MaxMhz);a.limitMhz=(std::max)(a.limitMhz,(uint32_t)x.MhzLimit);a.seen++;
        }
        totalSamples++;
        if(sample+1<samples)Sleep(intervalMs);
    }
    std::cout<<"{\"passed\":true,\"schema\":\"phoenix.forge.native-cpu-runtime/v1\",\"provider\":\"Windows CallNtPowerInformation\",\"sampling\":{\"samples\":"<<totalSamples<<",\"interval_ms\":"<<intervalMs<<"},\"logical_processor_count\":"<<logical<<",\"processor_groups\":[";
    for(DWORD g=0;g<groups;g++){if(g)std::cout<<",";std::cout<<"{\"group\":"<<g<<",\"active_processors\":"<<GetActiveProcessorCount((WORD)g)<<"}";}
    std::cout<<"],\"processors\":[";
    for(size_t i=0;i<agg.size();i++){
        if(i)std::cout<<",";auto &a=agg[i];double avg=a.seen?double(a.sum)/double(a.seen):0.0;double ratio=a.maxMhz?avg/double(a.maxMhz):0.0;
        std::cout<<"{\"sample_slot\":"<<i<<",\"os_processor_number\":"<<info[i].Number<<",\"max_mhz\":"<<a.maxMhz<<",\"mhz_limit\":"<<a.limitMhz<<",\"current_mhz_min\":"<<(a.min==UINT32_MAX?0:a.min)<<",\"current_mhz_avg\":"<<avg<<",\"current_mhz_max\":"<<a.max<<",\"avg_to_max_ratio\":"<<ratio<<",\"max_idle_state\":"<<info[i].MaxIdleState<<",\"current_idle_state\":"<<info[i].CurrentIdleState<<"}";
    }
    std::cout<<"],\"limitations\":[\"OS-reported CurrentMhz is not APERF/MPERF effective clock\",\"sample slots are not assigned to processor groups unless independently proven\",\"BCLK and multiplier are not inferred\"]}\n";return 0;
}
static int doCpuDeepInfo(){
    int r[4]{};__cpuid(r,0);unsigned maxLeaf=(unsigned)r[0];char vendor[13]{};memcpy(vendor,&r[1],4);memcpy(vendor+4,&r[3],4);memcpy(vendor+8,&r[2],4);
    __cpuid(r,0x80000000);unsigned maxExt=(unsigned)r[0];char brand[49]{};if(maxExt>=0x80000004)for(int i=0;i<3;i++){__cpuid(r,0x80000002+i);memcpy(brand+i*16,r,16);}while(*brand && (brand[strlen(brand)-1]==' '||brand[strlen(brand)-1]=='\0'))brand[strlen(brand)-1]='\0';
    __cpuid(r,1);unsigned sig=(unsigned)r[0],bf=(sig>>8)&15,bm=(sig>>4)&15,ef=(sig>>20)&255,em=(sig>>16)&15;unsigned family=bf==15?bf+ef:bf,model=(bf==6||bf==15)?(em<<4)+bm:bm,stepping=sig&15;unsigned leaf1ecx=(unsigned)r[2],leaf1edx=(unsigned)r[3];
    unsigned leaf7ebx=0,leaf7ecx=0,leaf7edx=0;if(maxLeaf>=7){__cpuidex(r,7,0);leaf7ebx=(unsigned)r[1];leaf7ecx=(unsigned)r[2];leaf7edx=(unsigned)r[3];}
    unsigned ext1ecx=0,ext1edx=0;if(maxExt>=0x80000001){__cpuid(r,0x80000001);ext1ecx=(unsigned)r[2];ext1edx=(unsigned)r[3];}
    unsigned physicalBits=0,virtualBits=0;if(maxExt>=0x80000008){__cpuid(r,0x80000008);physicalBits=(unsigned)r[0]&0xffu;virtualBits=((unsigned)r[0]>>8)&0xffu;}
    unsigned baseMHz=0,maxMHz=0,busMHz=0;if(maxLeaf>=0x16){__cpuid(r,0x16);baseMHz=(unsigned)r[0];maxMHz=(unsigned)r[1];busMHz=(unsigned)r[2];}
    unsigned tscDen=0,tscNum=0,crystalHz=0;if(maxLeaf>=0x15){__cpuid(r,0x15);tscDen=(unsigned)r[0];tscNum=(unsigned)r[1];crystalHz=(unsigned)r[2];}
    std::cout<<"{\"passed\":true,\"schema\":\"phoenix.forge.native-cpu/v1\",\"provider\":\"CPUID\",\"vendor\":\"";jsonEscape(vendor);std::cout<<"\",\"brand\":\"";jsonEscape(brand);std::cout<<"\",\"signature\":"<<sig<<",\"family\":"<<family<<",\"model\":"<<model<<",\"stepping\":"<<stepping<<",\"max_basic_leaf\":"<<maxLeaf<<",\"max_extended_leaf\":"<<maxExt;
    std::cout<<",\"address_width\":{\"physical_bits\":"<<physicalBits<<",\"virtual_bits\":"<<virtualBits<<"}";
    std::cout<<",\"frequency\":{\"base_mhz\":"<<baseMHz<<",\"max_mhz\":"<<maxMHz<<",\"bus_mhz\":"<<busMHz<<",\"tsc_denominator\":"<<tscDen<<",\"tsc_numerator\":"<<tscNum<<",\"crystal_hz\":"<<crystalHz<<"}";
    std::cout<<",\"features\":{";bool first=true;
    jsonBoolField("sse2",(leaf1edx&(1u<<26))!=0,first);jsonBoolField("sse3",(leaf1ecx&(1u<<0))!=0,first);jsonBoolField("pclmulqdq",(leaf1ecx&(1u<<1))!=0,first);jsonBoolField("ssse3",(leaf1ecx&(1u<<9))!=0,first);jsonBoolField("fma",(leaf1ecx&(1u<<12))!=0,first);jsonBoolField("sse4_1",(leaf1ecx&(1u<<19))!=0,first);jsonBoolField("sse4_2",(leaf1ecx&(1u<<20))!=0,first);jsonBoolField("x2apic",(leaf1ecx&(1u<<21))!=0,first);jsonBoolField("popcnt",(leaf1ecx&(1u<<23))!=0,first);jsonBoolField("aes",(leaf1ecx&(1u<<25))!=0,first);jsonBoolField("xsave",(leaf1ecx&(1u<<26))!=0,first);jsonBoolField("osxsave",(leaf1ecx&(1u<<27))!=0,first);jsonBoolField("avx",(leaf1ecx&(1u<<28))!=0,first);jsonBoolField("f16c",(leaf1ecx&(1u<<29))!=0,first);jsonBoolField("rdrand",(leaf1ecx&(1u<<30))!=0,first);
    jsonBoolField("fsgsbase",(leaf7ebx&(1u<<0))!=0,first);jsonBoolField("bmi1",(leaf7ebx&(1u<<3))!=0,first);jsonBoolField("avx2",(leaf7ebx&(1u<<5))!=0,first);jsonBoolField("smep",(leaf7ebx&(1u<<7))!=0,first);jsonBoolField("bmi2",(leaf7ebx&(1u<<8))!=0,first);jsonBoolField("erms",(leaf7ebx&(1u<<9))!=0,first);jsonBoolField("invpcid",(leaf7ebx&(1u<<10))!=0,first);jsonBoolField("rdseed",(leaf7ebx&(1u<<18))!=0,first);jsonBoolField("adx",(leaf7ebx&(1u<<19))!=0,first);jsonBoolField("smap",(leaf7ebx&(1u<<20))!=0,first);jsonBoolField("clflushopt",(leaf7ebx&(1u<<23))!=0,first);jsonBoolField("clwb",(leaf7ebx&(1u<<24))!=0,first);jsonBoolField("sha",(leaf7ebx&(1u<<29))!=0,first);jsonBoolField("umip",(leaf7ecx&(1u<<2))!=0,first);jsonBoolField("pku",(leaf7ecx&(1u<<3))!=0,first);jsonBoolField("avx512_vnni",(leaf7ecx&(1u<<11))!=0,first);jsonBoolField("serialize",(leaf7edx&(1u<<14))!=0,first);
    jsonBoolField("lahf_sahf",(ext1ecx&(1u<<0))!=0,first);jsonBoolField("lzcnt_abm",(ext1ecx&(1u<<5))!=0,first);jsonBoolField("nx",(ext1edx&(1u<<20))!=0,first);jsonBoolField("rdtscp",(ext1edx&(1u<<27))!=0,first);jsonBoolField("long_mode",(ext1edx&(1u<<29))!=0,first);std::cout<<"}";
    std::cout<<",\"caches\":[";bool firstCache=true;if(maxLeaf>=4){for(unsigned sub=0;sub<32;sub++){__cpuidex(r,4,(int)sub);unsigned eax=(unsigned)r[0],ebx=(unsigned)r[1],ecx=(unsigned)r[2],edx=(unsigned)r[3];unsigned type=eax&31u;if(type==0)break;unsigned level=(eax>>5)&7u;unsigned line=(ebx&0xfffu)+1u;unsigned partitions=((ebx>>12)&0x3ffu)+1u;unsigned ways=((ebx>>22)&0x3ffu)+1u;uint64_t sets=(uint64_t)ecx+1ull;uint64_t size=(uint64_t)line*partitions*ways*sets;unsigned shared=((eax>>14)&0xfffu)+1u;if(!firstCache)std::cout<<",";firstCache=false;std::cout<<"{\"level\":"<<level<<",\"type\":"<<type<<",\"type_name\":\""<<(type==1?"DATA":type==2?"INSTRUCTION":type==3?"UNIFIED":"UNKNOWN")<<"\",\"size_bytes\":"<<size<<",\"line_size\":"<<line<<",\"partitions\":"<<partitions<<",\"ways\":"<<ways<<",\"sets\":"<<sets<<",\"shared_logical_processors\":"<<shared<<",\"fully_associative\":"<<(((eax>>9)&1u)?"true":"false")<<",\"inclusive\":"<<(((edx>>1)&1u)?"true":"false")<<"}";}}
    std::cout<<"]";
    unsigned topoLeaf=maxLeaf>=0x1fu?0x1fu:(maxLeaf>=0x0bu?0x0bu:0u);std::cout<<",\"topology_leaf\":"<<topoLeaf<<",\"topology\":[";bool firstTopo=true;if(topoLeaf){for(unsigned sub=0;sub<32;sub++){__cpuidex(r,(int)topoLeaf,(int)sub);unsigned eax=(unsigned)r[0],ebx=(unsigned)r[1],ecx=(unsigned)r[2],edx=(unsigned)r[3];unsigned type=(ecx>>8)&0xffu;if(type==0||ebx==0)break;if(!firstTopo)std::cout<<",";firstTopo=false;std::cout<<"{\"subleaf\":"<<sub<<",\"level_number\":"<<(ecx&0xffu)<<",\"level_type\":"<<type<<",\"level_type_name\":\""<<(type==1?"SMT":type==2?"CORE":"OTHER")<<"\",\"shift\":"<<(eax&31u)<<",\"logical_processors\":"<<(ebx&0xffffu)<<",\"x2apic_id\":"<<edx<<"}";}}
    std::cout<<"]}"<<"\n";return 0;
}
#else
static int doDxgiInfo(){std::cout<<"{\"passed\":false,\"error\":\"DXGI is Windows-only\"}\n";return 11;}
static int doCpuInfo(){std::cout<<"{\"passed\":false,\"error\":\"CPUID helper is Windows/MSVC-only in this build\"}\n";return 12;}
static int doCpuDeepInfo(){std::cout<<"{\"passed\":false,\"error\":\"Deep CPUID helper is Windows/MSVC-only in this build\"}\n";return 12;}
static int doCpuClockInfo(unsigned,unsigned){std::cout<<"{\"passed\":false,\"error\":\"CPU runtime clock provider is Windows-only\"}\n";return 14;}
#endif


static std::vector<uint32_t> readSpv(const std::string& path){
    std::ifstream f(path,std::ios::binary|std::ios::ate);if(!f)throw std::runtime_error("compute shader stress.spv not found");auto n=f.tellg();if(n<=0||((size_t)n%4)!=0)throw std::runtime_error("invalid stress.spv");std::vector<uint32_t> w((size_t)n/4);f.seekg(0);f.read((char*)w.data(),n);return w;
}
static int doGpuComputeStress(Ctx&c,uint64_t mb,int seconds,uint32_t rounds,const std::string& shaderPath){
    VkDeviceSize sz=std::max<uint64_t>(16,mb)*1024ull*1024ull;sz=(sz/4)*4;Buf buf{},stage{};VkShaderModule sm{};VkDescriptorSetLayout dsl{};VkPipelineLayout pl{};VkPipeline pipe{};VkDescriptorPool dp{};VkDescriptorSet ds{};uint64_t submits=0;const uint32_t initial=0x13579BDFu;auto st=std::chrono::steady_clock::now();
    try{
        buf=makeBuffer(c,sz,VK_BUFFER_USAGE_STORAGE_BUFFER_BIT|VK_BUFFER_USAGE_TRANSFER_SRC_BIT|VK_BUFFER_USAGE_TRANSFER_DST_BIT,VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
        stage=makeBuffer(c,sz,VK_BUFFER_USAGE_TRANSFER_DST_BIT,VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT,VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
        fillCopyRange(c,buf,0,stage,sz,initial);
        auto code=readSpv(shaderPath);VkShaderModuleCreateInfo sci{VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO};sci.codeSize=code.size()*4;sci.pCode=code.data();if(vkCreateShaderModule(c.dev,&sci,nullptr,&sm)!=VK_SUCCESS)throw std::runtime_error("vkCreateShaderModule failed");
        VkDescriptorSetLayoutBinding b{};b.binding=0;b.descriptorType=VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;b.descriptorCount=1;b.stageFlags=VK_SHADER_STAGE_COMPUTE_BIT;VkDescriptorSetLayoutCreateInfo dlci{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO};dlci.bindingCount=1;dlci.pBindings=&b;if(vkCreateDescriptorSetLayout(c.dev,&dlci,nullptr,&dsl)!=VK_SUCCESS)throw std::runtime_error("vkCreateDescriptorSetLayout failed");
        VkPushConstantRange pr{};pr.stageFlags=VK_SHADER_STAGE_COMPUTE_BIT;pr.offset=0;pr.size=16;VkPipelineLayoutCreateInfo plci{VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO};plci.setLayoutCount=1;plci.pSetLayouts=&dsl;plci.pushConstantRangeCount=1;plci.pPushConstantRanges=&pr;if(vkCreatePipelineLayout(c.dev,&plci,nullptr,&pl)!=VK_SUCCESS)throw std::runtime_error("vkCreatePipelineLayout failed");
        VkPipelineShaderStageCreateInfo ss{VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO};ss.stage=VK_SHADER_STAGE_COMPUTE_BIT;ss.module=sm;ss.pName="main";VkComputePipelineCreateInfo cp{VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO};cp.stage=ss;cp.layout=pl;if(vkCreateComputePipelines(c.dev,VK_NULL_HANDLE,1,&cp,nullptr,&pipe)!=VK_SUCCESS)throw std::runtime_error("vkCreateComputePipelines failed");
        VkDescriptorPoolSize ps{VK_DESCRIPTOR_TYPE_STORAGE_BUFFER,1};VkDescriptorPoolCreateInfo dpci{VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO};dpci.maxSets=1;dpci.poolSizeCount=1;dpci.pPoolSizes=&ps;if(vkCreateDescriptorPool(c.dev,&dpci,nullptr,&dp)!=VK_SUCCESS)throw std::runtime_error("vkCreateDescriptorPool failed");VkDescriptorSetAllocateInfo dsai{VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO};dsai.descriptorPool=dp;dsai.descriptorSetCount=1;dsai.pSetLayouts=&dsl;if(vkAllocateDescriptorSets(c.dev,&dsai,&ds)!=VK_SUCCESS)throw std::runtime_error("vkAllocateDescriptorSets failed");VkDescriptorBufferInfo dbi{buf.b,0,sz};VkWriteDescriptorSet wr{VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET};wr.dstSet=ds;wr.dstBinding=0;wr.descriptorCount=1;wr.descriptorType=VK_DESCRIPTOR_TYPE_STORAGE_BUFFER;wr.pBufferInfo=&dbi;vkUpdateDescriptorSets(c.dev,1,&wr,0,nullptr);
        uint64_t elementCount=sz/4;uint32_t maxGroups=c.prop.limits.maxComputeWorkGroupCount[0];
        while(std::chrono::duration<double>(std::chrono::steady_clock::now()-st).count()<seconds){VkCommandBufferAllocateInfo ai{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};ai.commandPool=c.pool;ai.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY;ai.commandBufferCount=1;VkCommandBuffer cb{};vkAllocateCommandBuffers(c.dev,&ai,&cb);VkCommandBufferBeginInfo bi{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};bi.flags=VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;vkBeginCommandBuffer(cb,&bi);vkCmdBindPipeline(cb,VK_PIPELINE_BIND_POINT_COMPUTE,pipe);vkCmdBindDescriptorSets(cb,VK_PIPELINE_BIND_POINT_COMPUTE,pl,0,1,&ds,0,nullptr);for(uint64_t base=0;base<elementCount;){uint64_t remain=elementCount-base;uint32_t groups=(uint32_t)std::min<uint64_t>(maxGroups,(remain+255)/256);uint32_t pcv[4]={(uint32_t)submits,rounds,(uint32_t)base,(uint32_t)std::min<uint64_t>(elementCount,UINT32_MAX)};vkCmdPushConstants(cb,pl,VK_SHADER_STAGE_COMPUTE_BIT,0,sizeof(pcv),pcv);vkCmdDispatch(cb,groups,1,1);base+=uint64_t(groups)*256ull;}vkEndCommandBuffer(cb);VkSubmitInfo si{VK_STRUCTURE_TYPE_SUBMIT_INFO};si.commandBufferCount=1;si.pCommandBuffers=&cb;if(vkQueueSubmit(c.q,1,&si,VK_NULL_HANDLE)!=VK_SUCCESS)throw std::runtime_error("vkQueueSubmit compute failed");if(vkQueueWaitIdle(c.q)!=VK_SUCCESS)throw std::runtime_error("vkQueueWaitIdle compute failed");vkFreeCommandBuffers(c.dev,c.pool,1,&cb);submits++;}
    }catch(const std::exception&e){if(c.dev)vkDeviceWaitIdle(c.dev);if(dp)vkDestroyDescriptorPool(c.dev,dp,nullptr);if(pipe)vkDestroyPipeline(c.dev,pipe,nullptr);if(pl)vkDestroyPipelineLayout(c.dev,pl,nullptr);if(dsl)vkDestroyDescriptorSetLayout(c.dev,dsl,nullptr);if(sm)vkDestroyShaderModule(c.dev,sm,nullptr);if(stage.b)destroyBuffer(c,stage);if(buf.b)destroyBuffer(c,buf);std::cout<<"{\"passed\":false,\"error\":\"";jsonEscape(e.what());std::cout<<"\"}\n";return 13;}
    double sec=std::chrono::duration<double>(std::chrono::steady_clock::now()-st).count();vkDeviceWaitIdle(c.dev);copyRange(c,buf,0,stage,sz);
    uint64_t checked=0,errors=0;std::vector<uint64_t>bad;void* mapped=nullptr;uint64_t elements=(uint64_t)(sz/4),sampleCount=std::min<uint64_t>(64,elements);
    if(vkMapMemory(c.dev,stage.m,0,sz,0,&mapped)!=VK_SUCCESS)throw std::runtime_error("vkMapMemory compute verification failed");auto*actual=(uint32_t*)mapped;
    for(uint64_t sample=0;sample<sampleCount;sample++){uint64_t i=sampleCount==1?0:(sample*(elements-1))/(sampleCount-1);uint32_t expected=initial;for(uint64_t seed=0;seed<submits;seed++){expected=expected^(uint32_t)seed^(uint32_t)i;for(uint32_t r=0;r<rounds;r++)expected=(expected*1664525u+1013904223u)^(expected>>13u)^(expected<<7u);}checked++;if(actual[i]!=expected){errors++;if(bad.size()<16)bad.push_back(i);}}
    vkUnmapMemory(c.dev,stage.m);vkDestroyDescriptorPool(c.dev,dp,nullptr);vkDestroyPipeline(c.dev,pipe,nullptr);vkDestroyPipelineLayout(c.dev,pl,nullptr);vkDestroyDescriptorSetLayout(c.dev,dsl,nullptr);vkDestroyShaderModule(c.dev,sm,nullptr);destroyBuffer(c,stage);destroyBuffer(c,buf);
    std::cout<<"{\"passed\":"<<(errors?"false":"true")<<",\"status\":\""<<(errors?"COMPUTE_MISMATCH":"PASS")<<"\",\"device_name\":\"";jsonEscape(c.prop.deviceName);std::cout<<"\",\"mode\":\"vulkan_compute_verified\",\"requested_mb\":"<<mb<<",\"rounds_per_dispatch\":"<<rounds<<",\"dispatches\":"<<submits<<",\"duration_s\":"<<sec<<",\"correctness_verified\":"<<(errors?"false":"true")<<",\"verification_samples\":"<<checked<<",\"sample_errors\":"<<errors<<",\"bad_indices\":[";for(size_t i=0;i<bad.size();i++){if(i)std::cout<<",";std::cout<<bad[i];}std::cout<<"]}\n";return errors?24:0;
}

static void printHelp(){std::cout<<"Phoenix Forge Native 0.19.7\nCommands:\n  detect|info [--device N]\n  cpu-bench --seconds N [--threads N]\n  memory-bench --mb N --passes N\n  cache-bench [--mb N] [--accesses N]\n  vram-bandwidth --mb N --seconds N [--device N]\n  vram-test --mb N --passes N [--full-scan] [--continue-on-error] [--max-errors N] [--device N]\n  vram-map --chunk-mb N [--target-mb N] --passes N [--adaptive] [--min-chunk-mb N] [--reserve-mb N] [--full-scan] [--continue-on-error] [--max-errors N] [--device N]\n  gpu-stress --mb N --seconds N [--device N]\n  gpu-compute-stress --mb N --seconds N [--rounds N] [--shader PATH] [--device N]\n  dxgi-info\n  cpu-info\n  cpu-deep-info\n  cpu-clock-info [--samples N] [--interval-ms N]\n\nv0.19.7 hardens Windows runtime-clock compilation without depending on SDK-private PROCESSOR_POWER_INFORMATION/NTSTATUS typedef availability.\nv0.19.5 adds Windows per-logical-processor runtime clock sampling without claiming APERF/MPERF effective clocks.\nv0.19.4 adds deterministic cache/topology CPUID decoding.\n\nv0.18.0 adds per-device pre/post-flash evidence qualification without BIOS write capability.\nRanges remain logical Vulkan windows, not physical GDDR chip addresses.\n";}
int main(int argc, char** argv) {
    std::string cmd = argc > 1 ? argv[1] : "detect";
    if (cmd == "--help" || cmd == "-h" || cmd == "help") {
        printHelp();
        return 0;
    }

    uint64_t mb = 256;
    uint64_t chunkMb = 256;
    uint64_t targetMb = 0;
    uint64_t minChunkMb = 128;
    uint64_t reserveMb = 512;
    int passes = 2;
    int seconds = 20;
    uint32_t rounds = 64;
    std::string shaderPath = "stress.spv";
    uint32_t device = 0;
    bool fullScan = false;
    bool adaptive = false;
    bool continueOnError = false;
    uint64_t maxErrors = 64;
    uint64_t accesses = 2000000;
    unsigned threads = 0;
    unsigned samples = 5;
    unsigned intervalMs = 200;

    try {
        for (int i = 2; i < argc; ++i) {
            std::string arg = argv[i];
            auto requireValue = [&](const char* option) -> const char* {
                if (i + 1 >= argc) {
                    throw std::runtime_error(std::string("missing value for ") + option);
                }
                return argv[++i];
            };

            if (arg == "--mb") {
                mb = std::stoull(requireValue("--mb"));
            } else if (arg == "--chunk-mb") {
                chunkMb = std::stoull(requireValue("--chunk-mb"));
            } else if (arg == "--target-mb") {
                targetMb = std::stoull(requireValue("--target-mb"));
            } else if (arg == "--min-chunk-mb") {
                minChunkMb = std::stoull(requireValue("--min-chunk-mb"));
            } else if (arg == "--reserve-mb") {
                reserveMb = std::stoull(requireValue("--reserve-mb"));
            } else if (arg == "--passes") {
                passes = std::stoi(requireValue("--passes"));
            } else if (arg == "--seconds") {
                seconds = std::stoi(requireValue("--seconds"));
            } else if (arg == "--rounds") {
                rounds = static_cast<uint32_t>(std::stoul(requireValue("--rounds")));
            } else if (arg == "--max-errors") {
                maxErrors = (std::min<uint64_t>)(4096, std::stoull(requireValue("--max-errors")));
            } else if (arg == "--threads") {
                threads = static_cast<unsigned>(std::stoul(requireValue("--threads")));
            } else if (arg == "--accesses") {
                accesses = std::stoull(requireValue("--accesses"));
            } else if (arg == "--shader") {
                shaderPath = requireValue("--shader");
            } else if (arg == "--samples") {
                samples = static_cast<unsigned>(std::stoul(requireValue("--samples")));
            } else if (arg == "--interval-ms") {
                intervalMs = static_cast<unsigned>(std::stoul(requireValue("--interval-ms")));
            } else if (arg == "--device") {
                device = static_cast<uint32_t>(std::stoul(requireValue("--device")));
            } else if (arg == "--full-scan") {
                fullScan = true;
            } else if (arg == "--adaptive") {
                adaptive = true;
            } else if (arg == "--continue-on-error") {
                continueOnError = true;
            } else {
                throw std::runtime_error(std::string("unknown option: ") + arg);
            }
        }

        if (cmd == "dxgi-info") {
            return doDxgiInfo();
        }
        if (cmd == "cpu-info") {
            return doCpuInfo();
        }
        if (cmd == "cpu-deep-info") {
            return doCpuDeepInfo();
        }
        if (cmd == "cpu-clock-info") {
            return doCpuClockInfo(samples, intervalMs);
        }
        if (cmd == "cpu-bench") return phoenix::native_bench::cpu(seconds, threads);
        if (cmd == "memory-bench") return phoenix::native_bench::memory(mb, passes);
        if (cmd == "cache-bench") return phoenix::native_bench::cache(mb, accesses);

        Ctx ctx{};
        try {
            ctx = createCtx(device);
            int rc = 0;

            if (cmd == "detect" || cmd == "info") {
                rc = doDetect(ctx);
            } else if (cmd == "vram-test") {
                rc = doVram(ctx, mb, (std::max)(1, passes), fullScan, continueOnError, maxErrors);
            } else if (cmd == "vram-map") {
                rc = doVramMap(
                    ctx,
                    chunkMb,
                    targetMb,
                    (std::max)(1, passes),
                    fullScan,
                    adaptive,
                    minChunkMb,
                    reserveMb,
                    continueOnError,
                    maxErrors
                );
            } else if (cmd == "gpu-stress") {
                rc = doGpuStress(ctx, mb, (std::max)(1, seconds));
            } else if (cmd == "vram-bandwidth") {
                rc = doVramBandwidth(ctx, mb, (std::max)(1, seconds));
            } else if (cmd == "gpu-compute-stress") {
                rc = doGpuComputeStress(
                    ctx,
                    mb,
                    (std::max)(1, seconds),
                    (std::max<uint32_t>)(1u, rounds),
                    shaderPath
                );
            } else {
                std::cout << "{\"passed\":false,\"error\":\"unknown command\"}\n";
                rc = 4;
            }

            destroyCtx(ctx);
            return rc;
        } catch (const std::exception& e) {
            destroyCtx(ctx);
            std::cout << "{\"passed\":false,\"error\":\"";
            jsonEscape(e.what());
            std::cout << "\"}\n";
            return 2;
        }
    } catch (const std::exception& e) {
        std::cout << "{\"passed\":false,\"error\":\"";
        jsonEscape(e.what());
        std::cout << "\"}\n";
        return 3;
    }
}
