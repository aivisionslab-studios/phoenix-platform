#include "phoenix_sd_bridge.h"
#include "stable-diffusion.h"

#include <algorithm>
#include <cstring>
#include <memory>
#include <mutex>
#include <new>
#include <string>

struct phx_sd_handle {
    mutable std::mutex mutex;
    sd_ctx_t* ctx = nullptr;
    std::string last_error;
};

namespace {

constexpr const char* kBridgeVersion = "phoenix-sdcpp-native/0.2.0";

const char* empty_to_null(const char* value) {
    return (value && value[0] != '\0') ? value : nullptr;
}

void set_error(phx_sd_handle* handle, const std::string& message) {
    if (handle) {
        handle->last_error = message;
    }
}

void clear_error(phx_sd_handle* handle) {
    if (handle) {
        handle->last_error.clear();
    }
}

} // namespace

extern "C" {

const char* phx_sd_bridge_version(void) {
    return kBridgeVersion;
}

const char* phx_sd_system_info(void) {
    const char* info = sd_get_system_info();
    return info ? info : "";
}

int32_t phx_sd_physical_cores(void) {
    return sd_get_num_physical_cores();
}

phx_sd_handle* phx_sd_create(void) {
    try {
        return new phx_sd_handle();
    } catch (...) {
        return nullptr;
    }
}

void phx_sd_destroy(phx_sd_handle* handle) {
    if (!handle) {
        return;
    }
    phx_sd_unload_model(handle);
    delete handle;
}

int32_t phx_sd_load_model(phx_sd_handle* handle, const phx_sd_load_config* config) {
    if (!handle || !config) {
        return 0;
    }

    std::lock_guard<std::mutex> lock(handle->mutex);
    clear_error(handle);

    if (handle->ctx) {
        free_sd_ctx(handle->ctx);
        handle->ctx = nullptr;
    }

    sd_ctx_params_t params;
    sd_ctx_params_init(&params);

    params.model_path = empty_to_null(config->model_path);
    params.diffusion_model_path = empty_to_null(config->diffusion_model_path);
    params.clip_l_path = empty_to_null(config->clip_l_path);
    params.clip_g_path = empty_to_null(config->clip_g_path);
    params.t5xxl_path = empty_to_null(config->t5xxl_path);
    params.llm_path = empty_to_null(config->llm_path);
    params.vae_path = empty_to_null(config->vae_path);
    params.taesd_path = empty_to_null(config->taesd_path);
    params.backend = empty_to_null(config->backend);
    params.params_backend = empty_to_null(config->params_backend);
    params.max_vram = empty_to_null(config->max_vram);
    params.split_mode = empty_to_null(config->split_mode);
    params.model_args = empty_to_null(config->model_args);

    if (config->n_threads > 0) {
        params.n_threads = config->n_threads;
    }
    params.auto_fit = config->auto_fit != 0;
    params.stream_layers = config->stream_layers != 0;
    params.eager_load = config->eager_load != 0;
    params.enable_mmap = config->enable_mmap != 0;
    params.diffusion_flash_attn = config->diffusion_flash_attn != 0;
    params.diffusion_conv_direct = config->diffusion_conv_direct != 0;
    params.vae_conv_direct = config->vae_conv_direct != 0;
    if (config->vae_format >= SD_VAE_FORMAT_AUTO &&
        config->vae_format < SD_VAE_FORMAT_COUNT) {
        params.vae_format = static_cast<sd_vae_format_t>(config->vae_format);
    }

    try {
        handle->ctx = new_sd_ctx(&params);
    } catch (const std::exception& ex) {
        set_error(handle, std::string("new_sd_ctx exception: ") + ex.what());
        return 0;
    } catch (...) {
        set_error(handle, "new_sd_ctx failed with an unknown native exception");
        return 0;
    }

    if (!handle->ctx) {
        set_error(handle, "stable-diffusion.cpp returned a null context while loading the model");
        return 0;
    }

    if (!sd_ctx_supports_image_generation(handle->ctx)) {
        free_sd_ctx(handle->ctx);
        handle->ctx = nullptr;
        set_error(handle, "loaded context does not support image generation");
        return 0;
    }

    return 1;
}

int32_t phx_sd_is_loaded(const phx_sd_handle* handle) {
    return handle && handle->ctx ? 1 : 0;
}

void phx_sd_unload_model(phx_sd_handle* handle) {
    if (!handle) {
        return;
    }
    std::lock_guard<std::mutex> lock(handle->mutex);
    if (handle->ctx) {
        free_sd_ctx(handle->ctx);
        handle->ctx = nullptr;
    }
}

int32_t phx_sd_generate(phx_sd_handle* handle,
                        const phx_sd_generate_config* config,
                        phx_sd_image* image_out) {
    if (!handle || !config || !image_out) {
        return 0;
    }

    std::lock_guard<std::mutex> lock(handle->mutex);
    clear_error(handle);
    std::memset(image_out, 0, sizeof(*image_out));

    if (!handle->ctx) {
        set_error(handle, "no model is loaded");
        return 0;
    }
    if (!config->prompt || config->prompt[0] == '\0') {
        set_error(handle, "prompt is empty");
        return 0;
    }

    sd_img_gen_params_t params;
    sd_img_gen_params_init(&params);

    params.prompt = config->prompt;
    params.negative_prompt = empty_to_null(config->negative_prompt);
    params.width = config->width > 0 ? config->width : 512;
    params.height = config->height > 0 ? config->height : 512;
    params.seed = config->seed;
    params.batch_count = config->batch_count > 0 ? config->batch_count : 1;
    params.clip_skip = config->clip_skip;

    if (config->steps > 0) {
        params.sample_params.sample_steps = config->steps;
    }
    if (config->cfg_scale >= 0.0f) {
        params.sample_params.guidance.txt_cfg = config->cfg_scale;
    }
    if (config->distilled_guidance >= 0.0f) {
        params.sample_params.guidance.distilled_guidance = config->distilled_guidance;
    }

    const char* sampler = empty_to_null(config->sampler);
    if (sampler) {
        const sample_method_t parsed = str_to_sample_method(sampler);
        if (parsed == SAMPLE_METHOD_COUNT) {
            set_error(handle, std::string("unknown sampler: ") + sampler);
            return 0;
        }
        params.sample_params.sample_method = parsed;
    } else {
        params.sample_params.sample_method = sd_get_default_sample_method(handle->ctx);
    }

    const char* scheduler = empty_to_null(config->scheduler);
    if (scheduler) {
        const scheduler_t parsed = str_to_scheduler(scheduler);
        if (parsed == SCHEDULER_COUNT) {
            set_error(handle, std::string("unknown scheduler: ") + scheduler);
            return 0;
        }
        params.sample_params.scheduler = parsed;
    } else {
        params.sample_params.scheduler = sd_get_default_scheduler(handle->ctx, params.sample_params.sample_method);
    }

    if (config->vae_tiling != 0) {
        params.vae_tiling_params.enabled = true;
        if (config->vae_tile_size_x > 0) {
            params.vae_tiling_params.tile_size_x = config->vae_tile_size_x;
        }
        if (config->vae_tile_size_y > 0) {
            params.vae_tiling_params.tile_size_y = config->vae_tile_size_y;
        }
        if (config->vae_target_overlap > 0.0f) {
            params.vae_tiling_params.target_overlap = config->vae_target_overlap;
        }
    }

    sd_image_t* images = nullptr;
    int image_count = 0;
    bool ok = false;
    try {
        ok = generate_image(handle->ctx, &params, &images, &image_count);
    } catch (const std::exception& ex) {
        set_error(handle, std::string("generate_image exception: ") + ex.what());
        return 0;
    } catch (...) {
        set_error(handle, "generate_image failed with an unknown native exception");
        return 0;
    }

    if (!ok || !images || image_count <= 0 || !images[0].data) {
        if (images) {
            free_sd_images(images, image_count);
        }
        set_error(handle, "stable-diffusion.cpp did not return an image");
        return 0;
    }

    const sd_image_t& first = images[0];
    const size_t data_size = static_cast<size_t>(first.width) *
                             static_cast<size_t>(first.height) *
                             static_cast<size_t>(first.channel);

    uint8_t* copied = new (std::nothrow) uint8_t[data_size];
    if (!copied) {
        free_sd_images(images, image_count);
        set_error(handle, "failed to allocate output image buffer");
        return 0;
    }
    std::memcpy(copied, first.data, data_size);

    image_out->width = first.width;
    image_out->height = first.height;
    image_out->channels = first.channel;
    image_out->data = copied;
    image_out->data_size = data_size;

    free_sd_images(images, image_count);
    return 1;
}

void phx_sd_free_image(phx_sd_image* image) {
    if (!image) {
        return;
    }
    delete[] image->data;
    image->data = nullptr;
    image->data_size = 0;
    image->width = 0;
    image->height = 0;
    image->channels = 0;
}

void phx_sd_cancel(phx_sd_handle* handle) {
    if (!handle || !handle->ctx) {
        return;
    }
    sd_cancel_generation(handle->ctx, SD_CANCEL_ALL);
}

const char* phx_sd_last_error(const phx_sd_handle* handle) {
    if (!handle) {
        return "invalid Phoenix SD handle";
    }
    return handle->last_error.c_str();
}

} // extern "C"
