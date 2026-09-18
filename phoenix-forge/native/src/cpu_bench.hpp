#pragma once
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <numeric>
#include <thread>
#include <vector>

namespace phoenix::native_bench {
using Clock = std::chrono::steady_clock;

inline int cpu(int seconds, unsigned requestedThreads) {
    const unsigned available = std::max(1u, std::thread::hardware_concurrency());
    const unsigned threads = std::clamp(requestedThreads ? requestedThreads : available, 1u, available * 2u);
    const auto deadline = Clock::now() + std::chrono::seconds(std::clamp(seconds, 1, 900));
    std::vector<uint64_t> operations(threads), checksums(threads);
    std::vector<std::thread> workers;
    const auto started = Clock::now();
    for (unsigned t = 0; t < threads; ++t) workers.emplace_back([&, t] {
        uint64_t x = 0x9E3779B97F4A7C15ull ^ (uint64_t(t) << 32), n = 0;
        while (Clock::now() < deadline) {
            for (int i = 0; i < 4096; ++i) {
                x ^= x << 13; x ^= x >> 7; x ^= x << 17;
                x = x * 0xD1342543DE82EF95ull + 0x94D049BB133111EBull; ++n;
            }
        }
        operations[t] = n; checksums[t] = x;
    });
    for (auto& worker : workers) worker.join();
    const double elapsed = std::chrono::duration<double>(Clock::now() - started).count();
    const uint64_t total = std::accumulate(operations.begin(), operations.end(), uint64_t{});
    std::cout << "{\"passed\":" << (total ? "true" : "false") << ",\"mode\":\"native_cpu_integer\",\"threads\":" << threads
              << ",\"hardware_threads\":" << available << ",\"duration_s\":" << elapsed << ",\"operations\":" << total
              << ",\"operations_per_second\":" << (elapsed ? total / elapsed : 0) << ",\"checksums\":[";
    for (size_t i=0;i<checksums.size();++i) { if(i) std::cout << ','; std::cout << checksums[i]; }
    std::cout << "]}\n"; return total ? 0 : 20;
}

inline int memory(uint64_t mb, int passes) {
    mb = std::clamp<uint64_t>(mb, 1, 16384); passes = std::clamp(passes, 1, 100);
    const size_t bytes = size_t(mb) * 1024u * 1024u;
    try {
        std::vector<uint8_t> source(bytes), destination(bytes);
        for (size_t i=0;i<bytes;++i) source[i] = uint8_t((i * 131u + 17u) & 255u);
        const auto started=Clock::now();
        for(int p=0;p<passes;++p) std::memcpy(destination.data(),source.data(),bytes);
        const double elapsed=std::chrono::duration<double>(Clock::now()-started).count();
        const bool ok=destination==source; uint64_t checksum=1469598103934665603ull;
        for(size_t i=0;i<bytes;i+=4096) { checksum^=destination[i]; checksum*=1099511628211ull; }
        const double traffic=double(bytes)*passes*2.0/1e9;
        std::cout<<"{\"passed\":"<<(ok?"true":"false")<<",\"mode\":\"native_memory_copy\",\"size_mb\":"<<mb
                 <<",\"passes\":"<<passes<<",\"duration_s\":"<<elapsed<<",\"bandwidth_gbps\":"<<(elapsed?traffic/elapsed:0)
                 <<",\"correctness_verified\":"<<(ok?"true":"false")<<",\"checksum\":"<<checksum<<"}\n"; return ok?0:21;
    } catch(const std::bad_alloc&) { std::cout<<"{\"passed\":false,\"status\":\"ALLOCATION_FAILED\",\"size_mb\":"<<mb<<"}\n"; return 22; }
}

inline int cache(uint64_t maxMb, uint64_t accesses) {
    maxMb=std::clamp<uint64_t>(maxMb,1,1024); accesses=std::clamp<uint64_t>(accesses,10000,1000000000ull);
    const uint64_t candidates[]={32*1024ull,256*1024ull,1024*1024ull,8*1024*1024ull,32*1024*1024ull,128*1024*1024ull};
    std::cout<<"{\"passed\":true,\"mode\":\"native_cache_latency\",\"accesses_per_size\":"<<accesses<<",\"levels\":["; bool first=true;
    volatile uint32_t sink=0;
    for(uint64_t bytes:candidates){ if(bytes>maxMb*1024ull*1024ull)continue; size_t count=bytes/sizeof(uint32_t);std::vector<uint32_t> chain(count);size_t step=1009;while(std::gcd(step,count)!=1)step+=2;for(size_t i=0;i<count;++i)chain[i]=uint32_t((i+step)%count);uint32_t pos=0;auto st=Clock::now();for(uint64_t i=0;i<accesses;++i)pos=chain[pos];double sec=std::chrono::duration<double>(Clock::now()-st).count();sink^=pos;if(!first)std::cout<<',';first=false;std::cout<<"{\"size_bytes\":"<<bytes<<",\"nanoseconds_per_access\":"<<(sec*1e9/accesses)<<",\"million_accesses_per_second\":"<<(accesses/sec/1e6)<<",\"checksum\":"<<pos<<'}';}
    std::cout<<"],\"sink\":"<<sink<<"}\n";return 0;
}
}
