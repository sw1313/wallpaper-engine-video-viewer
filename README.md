# Wallpaper Engine 视频查看器
用AI生成的Wallpaper Engine视频查看器</br>
照原库修改添加部分功能

## 使用方法
windows系统下运行
第一次运行时会让你选择Wallpaper Engine的下载路径
一般在C:\Program Files (x86)\Steam\steamapps\workshop\content\一串数字\

选择后会在程序目录下生成config.txt文件，里面记录了刚刚选择的路径
需要更改路径就修改这个文件，或者删除它重新运行程序

左键双击以默认打开方式打开这个视频
右键双击用系统资源管理器打开这个视频所在文件夹

输入页码需要输入指定页码，回车应用

新增：  
1.读取config.json文件识别用户文件夹分类  
2.批量播放（使用m3u播放列表，确保有视频播放器可以读取，比如potplayer，建议用mpv，开启速度快很多，如果是HDR显示器需要在`C:\Users\(用户)\AppData\Roaming\mpv\mpv.conf`（没有的新建）写入`vo=sdl`要不显示不正常。  
3.打开文件所在文件夹  
4.删除（有些文件取消订阅了但是we未正常删除）  
5.打开创意工坊链接（方便取消订阅，由于没有api，只能手动，如果想稍微再快点，参考：https://github.com/sw1313/we-video-preview  
这样在软件里就可以快速预览，看到不想要的就顺手右键取消订阅了）  
  
不适合展出，图片就不单独展示了  
  
推荐在2k分辨率下使用  
webui版本(容器部署，多端浏览）：https://github.com/sw1313/wallpaper-engine-video-viewer-webui
