cmake_minimum_required(VERSION 3.20)
project(phoenix_smbus_windows LANGUAGES CXX)
add_executable(phoenix-smbus-windows main.cpp)
target_compile_features(phoenix-smbus-windows PRIVATE cxx_std_17)
target_compile_definitions(phoenix-smbus-windows PRIVATE UNICODE _UNICODE WIN32_LEAN_AND_MEAN NOMINMAX)

if(MSVC)
  target_compile_options(phoenix-smbus-windows PRIVATE /W4 /EHsc /WX)
endif()
