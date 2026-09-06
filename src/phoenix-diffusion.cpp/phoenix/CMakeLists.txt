add_library(phoenix_sd_bridge SHARED
    src/phoenix_sd_bridge.cpp
)

target_compile_definitions(phoenix_sd_bridge PRIVATE PHOENIX_SD_BRIDGE_BUILD)
target_include_directories(phoenix_sd_bridge
    PUBLIC  "${CMAKE_CURRENT_SOURCE_DIR}/include"
    PRIVATE "${CMAKE_SOURCE_DIR}/include"
)
target_link_libraries(phoenix_sd_bridge PRIVATE stable-diffusion)

if(MSVC)
    target_compile_options(phoenix_sd_bridge PRIVATE /utf-8 /W4)
else()
    target_compile_options(phoenix_sd_bridge PRIVATE -Wall -Wextra -Wpedantic)
endif()

set_target_properties(phoenix_sd_bridge PROPERTIES
    OUTPUT_NAME "phoenix_sd_bridge"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
    ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/lib"
)
