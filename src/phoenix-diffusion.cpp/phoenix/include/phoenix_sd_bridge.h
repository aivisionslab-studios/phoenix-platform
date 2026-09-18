#pragma once

#include <stdint.h>
#include <stddef.h>

#ifdef _WIN32
  #ifdef PHOENIX_SD_BRIDGE_BUILD
    #define PHX_SD_API __declspec(dllexport)
  #else
    #define PHX_SD_API __declspec(dllimport)
  #endif
#else
  #define PHX_SD_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef struct phx_sd_handle phx_sd_handle;

typedef struct phx_sd_load_config {
    const char* model_path;
    const char* diffusion_model_path;
    const char* clip_l_path;
    const char* clip_g_path;
    const char* t5xxl_path;
    const char* vae_path;
    const char* taesd_path;
    const char* backend;
    const char* params_backend;
    const char* max_vram;
    const char* split_mode;
    const char* model_args;
    int32_t n_threads;
    int32_t auto_fit;
    int32_t stream_layers;
    int32_t eager_load;
    int32_t enable_mmap;
    int32_t diffusion_flash_attn;
    int32_t diffusion_conv_direct;
    int32_t vae_conv_direct;
    /* ABI 0.2: appended so an older 0.1 DLL can still read the prefix. */
    const char* llm_path;
    int32_t vae_format;
} phx_sd_load_config;

typedef struct phx_sd_generate_config {
    const char* prompt;
    const char* negative_prompt;
    const char* sampler;
    const char* scheduler;
    int32_t width;
    int32_t height;
    int32_t steps;
    float cfg_scale;
    float distilled_guidance;
    int64_t seed;
    int32_t batch_count;
    int32_t clip_skip;
    int32_t vae_tiling;
    int32_t vae_tile_size_x;
    int32_t vae_tile_size_y;
    float vae_target_overlap;
} phx_sd_generate_config;

typedef struct phx_sd_image {
    uint32_t width;
    uint32_t height;
    uint32_t channels;
    uint8_t* data;
    size_t data_size;
} phx_sd_image;

PHX_SD_API const char* phx_sd_bridge_version(void);
PHX_SD_API const char* phx_sd_system_info(void);
PHX_SD_API int32_t phx_sd_physical_cores(void);

PHX_SD_API phx_sd_handle* phx_sd_create(void);
PHX_SD_API void phx_sd_destroy(phx_sd_handle* handle);
PHX_SD_API int32_t phx_sd_load_model(phx_sd_handle* handle, const phx_sd_load_config* config);
PHX_SD_API int32_t phx_sd_is_loaded(const phx_sd_handle* handle);
PHX_SD_API void phx_sd_unload_model(phx_sd_handle* handle);
PHX_SD_API int32_t phx_sd_generate(phx_sd_handle* handle,
                                   const phx_sd_generate_config* config,
                                   phx_sd_image* image_out);
PHX_SD_API void phx_sd_free_image(phx_sd_image* image);
PHX_SD_API void phx_sd_cancel(phx_sd_handle* handle);
PHX_SD_API const char* phx_sd_last_error(const phx_sd_handle* handle);

#ifdef __cplusplus
}
#endif
