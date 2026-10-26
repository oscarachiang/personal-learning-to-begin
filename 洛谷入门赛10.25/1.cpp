#include <bits/stdc++.h>
using namespace std;
int main() {
    int a,b;
    cin>>a>>b;
    if(a*0.6>b){
        cout<<"-1";
    }
    else{
        if(a<=b){
            cout<<"1"<<" ";
            printf("%.2f",a*1.0);
            return 0;
        }
        if(a*0.9<=b){
            cout<<"3"<<" ";
            printf("%.2f",a*0.9);
            return 0;
        }
        if(a*0.8<=b){
            cout<<"4"<<" ";
            printf("%.2f",a*0.8);
            return 0;
        }
        if(a*0.7<=b){
            cout<<"5"<<" ";
            printf("%.2f",a*0.7);
            return 0;
        }
        if(a*0.6<=b){
            cout<<"6"<<" ";
            printf("%.2f",a*0.6);
            return 0;
        }
    }
    return 0;
}
