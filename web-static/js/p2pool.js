(function(){
    var app = angular.module('p2pool', []);
    
    app.controller('p2pool-controller', function($http, $scope){
        
        this.site_title = "P2Pool";
        this.frontpage = $scope;
        
        function LoadData(frontpage) {
            $http.get('../web/version').then(function(r){
                frontpage.version = r.data;
            })
            $http.get('../web/currency_info').then(function(r){
                frontpage.currency_info = r.data;
            })
        };
        
        LoadData(this.frontpage);

        
    });
})();

